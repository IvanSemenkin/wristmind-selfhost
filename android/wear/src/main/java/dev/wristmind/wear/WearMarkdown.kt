package dev.wristmind.wear

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

internal sealed interface MarkdownBlock {
    data class Heading(val level: Int, val text: String) : MarkdownBlock
    data class Paragraph(val text: String) : MarkdownBlock
    data class ListItem(val marker: String, val text: String) : MarkdownBlock
    data class Quote(val text: String) : MarkdownBlock
    data class Code(val text: String) : MarkdownBlock
    data class Math(val source: String) : MarkdownBlock

    /**
     * A Markdown table already normalized into the vertical Wear shape: the
     * renderer turns it into a card, never into a horizontal grid.
     *
     * [header] is empty when the table had no header/separator row. [rows] keep
     * their original columns (already padded to the same width).
     */
    data class Table(val header: List<String>, val rows: List<List<String>>) : MarkdownBlock

    data object Divider : MarkdownBlock
}

/**
 * Standalone bold line, e.g. `**Использованные источники**`.
 *
 * The surrounding whitespace is limited to a single line on purpose: an earlier
 * `\s*` version could start matching on an earlier blank line, and the heading
 * itself is now matched against an explicit allow-list instead of any line that
 * merely mentions "источник".
 */
private val BOLD_HEADING_LINE = Regex("(?m)^[ \\t]*\\*\\*([^*\\n]+)\\*\\*[ \\t]*$")

/**
 * Headings the server (and older clients) actually use for the generated source
 * list. `server/src/wristmind_server/web_search.py` appends
 * `**Использованные источники**`; the other two are the historically emitted
 * variants. A model-authored line such as `**Источник**` — singular, a real
 * reference inside the answer — is deliberately not in this set.
 */
private val SEARCH_SOURCE_HEADINGS = setOf(
    "использованные источники",
    "источники поиска",
    "источники",
)

private val DIVIDER_LINE = Regex("^[-*_]{3,}$")
private val HEADING_LINE = Regex("^#{1,4}\\s+.+")
private val BULLET_ITEM = Regex("^[-*]\\s+.+")
private val ORDERED_ITEM = Regex("^\\d+[.)]\\s+.+")

/** One cell of a `|---|---|` alignment row. */
private val TABLE_SEPARATOR_CELL = Regex("^:?-{2,}:?$")

/** Markdown characters that can be backslash-escaped in TeX/text. */
private val ESCAPED_LITERALS = setOf('%', '$', '&', '_', '#', '{', '}')

/** The server keeps source links for web and API clients; a round watch keeps only the answer. */
internal fun withoutSearchSources(source: String): String {
    val heading = BOLD_HEADING_LINE.findAll(source).firstOrNull { match ->
        match.groupValues[1].trim().lowercase() in SEARCH_SOURCE_HEADINGS
    } ?: return source
    return source.substring(0, heading.range.first).trimEnd()
}

/**
 * Parses an answer into Wear-native blocks.
 *
 * Fenced code is captured first and kept verbatim, so a table-looking line inside
 * ``` never reaches the table normalizer. Tables are the second special case:
 * they become a structured [MarkdownBlock.Table] instead of raw `|` lines.
 *
 * A blank answer yields no blocks at all — callers must not create an empty card
 * for it.
 */
internal fun parseMarkdown(source: String): List<MarkdownBlock> {
    if (source.isBlank()) return emptyList()
    val lines = source.replace("\r\n", "\n").split("\n")
    val blocks = mutableListOf<MarkdownBlock>()
    val paragraph = mutableListOf<String>()
    val code = mutableListOf<String>()
    val math = mutableListOf<String>()
    var inCode = false
    var inMath = false
    var mathFence: String? = null

    fun flushParagraph() {
        if (paragraph.isNotEmpty()) {
            blocks += MarkdownBlock.Paragraph(paragraph.joinToString(" ").trim())
            paragraph.clear()
        }
    }

    var index = 0
    while (index < lines.size) {
        val raw = lines[index]
        val trimmed = raw.trim()

        // Fenced code first: everything inside stays byte-for-byte.
        if (trimmed.startsWith("```")) {
            if (inCode) {
                blocks += MarkdownBlock.Code(code.joinToString("\n"))
                code.clear()
            } else {
                flushParagraph()
            }
            inCode = !inCode
            index++
            continue
        }
        if (inCode) {
            code += raw
            index++
            continue
        }

        // Display math: `$$ … $$` or `\[ … \]`, on one line or across several.
        val display = displayMathLine(trimmed)
        val closesDisplay = inMath && when (mathFence) {
            "$$" -> trimmed.startsWith("$$")
            "\\[" -> trimmed.startsWith("\\]")
            else -> false
        }
        if (closesDisplay) {
            blocks += MarkdownBlock.Math(math.joinToString("\n").trim())
            math.clear()
            inMath = false
            mathFence = null
            index++
            continue
        }
        if (display != null && !inMath) {
            if (display.inline != null) {
                flushParagraph()
                blocks += MarkdownBlock.Math(display.inline)
            } else {
                flushParagraph()
                inMath = true
                mathFence = display.open
            }
            index++
            continue
        }
        if (inMath) {
            // A display formula keeps its line breaks; joining with spaces made
            // multi-line systems unreadable.
            math += raw.trim()
            index++
            continue
        }

        if (trimmed.isEmpty()) {
            flushParagraph()
            index++
            continue
        }
        if (trimmed.matches(DIVIDER_LINE)) {
            flushParagraph()
            blocks += MarkdownBlock.Divider
            index++
            continue
        }

        // Tables: collect the whole run of pipe-bearing lines before deciding,
        // so a two-row table without a separator is still recognized.
        if (isTableCandidate(raw)) {
            val run = mutableListOf<String>()
            while (index < lines.size && isTableCandidate(lines[index])) {
                run += lines[index]
                index++
            }
            flushParagraph()
            val table = run.toTableBlock()
            if (table != null) {
                blocks += table
            } else {
                paragraph += run.joinToString(" ") { it.trim() }
            }
            continue
        }

        when {
            trimmed.startsWith("$") && trimmed.endsWith("$") && trimmed.length > 2 -> {
                flushParagraph()
                blocks += MarkdownBlock.Math(trimmed.drop(1).dropLast(1))
            }
            trimmed.matches(HEADING_LINE) -> {
                flushParagraph()
                val level = trimmed.takeWhile { it == '#' }.length
                blocks += MarkdownBlock.Heading(level, trimmed.drop(level).trim())
            }
            trimmed.matches(BULLET_ITEM) -> {
                flushParagraph()
                blocks += MarkdownBlock.ListItem("•", trimmed.drop(2).trim())
            }
            trimmed.matches(ORDERED_ITEM) -> {
                flushParagraph()
                val marker = trimmed.substringBefore(' ').trimEnd('.', ')') + "."
                blocks += MarkdownBlock.ListItem(marker, trimmed.substringAfter(' ').trim())
            }
            trimmed.startsWith("> ") -> {
                flushParagraph()
                blocks += MarkdownBlock.Quote(trimmed.drop(2).trim())
            }
            else -> paragraph += trimmed
        }
        index++
    }
    if (inCode && code.isNotEmpty()) blocks += MarkdownBlock.Code(code.joinToString("\n"))
    if (inMath && math.isNotEmpty()) blocks += MarkdownBlock.Math(math.joinToString("\n").trim())
    flushParagraph()
    return blocks
}

private class DisplayMathLine(val open: String, val inline: String?)

/**
 * The opening line of a display formula.
 *
 * A line that carries both delimiters is a complete formula ([inline]); a lone
 * `$$` / `\[` opens a block whose body runs until the matching closer.
 */
private fun displayMathLine(trimmed: String): DisplayMathLine? = when {
    trimmed.startsWith("$$") -> DisplayMathLine(
        open = "$$",
        inline = if (trimmed.length > 4 && trimmed.endsWith("$$")) {
            trimmed.substring(2, trimmed.length - 2).trim()
        } else {
            null
        },
    )
    trimmed.startsWith("\\[") -> DisplayMathLine(
        open = "\\[",
        inline = if (trimmed.length > 4 && trimmed.endsWith("\\]")) {
            trimmed.substring(2, trimmed.length - 2).trim()
        } else {
            null
        },
    )
    else -> null
}

/**
 * Compact flat rendering of an answer for the three-line feed preview.
 *
 * Block structure is flattened (headings lose `#`, lists keep a bullet, tables
 * become one pipe-free line) and inline markers are resolved by [inlineMarkdown].
 * Code fences are dropped while their contents are kept as plain text.
 */
internal fun previewMarkdown(source: String, accent: Color = SignalBlue): AnnotatedString =
    inlineMarkdown(previewPlainText(source), accent)

internal fun previewPlainText(source: String): String {
    if (source.isBlank()) return ""
    val lines = source.replace("\r\n", "\n").split("\n")
    val out = mutableListOf<String>()
    val paragraph = mutableListOf<String>()
    val code = mutableListOf<String>()
    val math = mutableListOf<String>()
    var inCode = false
    var inMath = false

    fun flushParagraph() {
        if (paragraph.isNotEmpty()) {
            out += paragraph.joinToString(" ")
            paragraph.clear()
        }
    }

    var index = 0
    while (index < lines.size) {
        val raw = lines[index]
        val trimmed = raw.trim()

        if (trimmed.startsWith("```")) {
            if (inCode) {
                if (code.isNotEmpty()) out += code.joinToString(" ")
                code.clear()
            } else {
                flushParagraph()
            }
            inCode = !inCode
            index++
            continue
        }
        if (inCode) {
            if (trimmed.isNotEmpty()) code += trimmed
            index++
            continue
        }

        if (trimmed.startsWith("$$")) {
            if (inMath) {
                if (math.isNotEmpty()) {
                    flushParagraph()
                    out += mathDisplay(math.joinToString(" "))
                }
                math.clear()
            } else {
                flushParagraph()
            }
            inMath = !inMath
            index++
            continue
        }
        if (inMath) {
            math += trimmed
            index++
            continue
        }

        if (trimmed.isEmpty()) {
            flushParagraph()
            index++
            continue
        }
        if (trimmed.matches(DIVIDER_LINE)) {
            flushParagraph()
            index++
            continue
        }

        if (isTableCandidate(raw)) {
            val run = mutableListOf<String>()
            while (index < lines.size && isTableCandidate(lines[index])) {
                run += lines[index]
                index++
            }
            flushParagraph()
            val table = run.toTableBlock()
            if (table != null) {
                out += table.previewLine()
            } else {
                paragraph += run.joinToString(" ") { it.trim() }
            }
            continue
        }

        when {
            trimmed.startsWith("$") && trimmed.endsWith("$") && trimmed.length > 2 -> {
                flushParagraph()
                out += mathDisplay(trimmed.drop(1).dropLast(1))
            }
            trimmed.matches(HEADING_LINE) -> {
                flushParagraph()
                out += trimmed.dropWhile { it == '#' }.trim()
            }
            trimmed.matches(BULLET_ITEM) -> {
                flushParagraph()
                out += "• ${trimmed.drop(2).trim()}"
            }
            trimmed.matches(ORDERED_ITEM) -> {
                flushParagraph()
                val marker = trimmed.substringBefore(' ').trimEnd('.', ')') + "."
                out += "$marker ${trimmed.substringAfter(' ').trim()}"
            }
            trimmed.startsWith("> ") -> {
                flushParagraph()
                out += trimmed.drop(2).trim()
            }
            else -> paragraph += trimmed
        }
        index++
    }
    if (inCode && code.isNotEmpty()) out += code.joinToString(" ")
    if (inMath && math.isNotEmpty()) out += mathDisplay(math.joinToString(" "))
    flushParagraph()
    return out.joinToString(" ").trim()
}

// ---------------------------------------------------------------------------
// Table normalization
// ---------------------------------------------------------------------------

/** A line that could belong to a Markdown table: it has a pipe and at least two cells. */
private fun isTableCandidate(line: String): Boolean {
    val trimmed = line.trim()
    if (trimmed.isEmpty() || '|' !in trimmed) return false
    return trimmed.splitTableCells().size >= 2
}

private fun String.splitTableCells(): List<String> =
    trim().removePrefix("|").removeSuffix("|").split('|').map { it.trim() }

private fun List<String>.toTableBlock(): MarkdownBlock.Table? {
    if (isEmpty()) return null

    // A single pipe-bearing line is only trusted when it is unmistakably a row
    // (`| a | b |`). Two or more consecutive rows are always a table.
    val firstLine = first().trim()
    val looksLikeTable = size >= 2 || (firstLine.startsWith("|") && firstLine.endsWith("|"))
    if (!looksLikeTable) return null

    val rows = map { it.splitTableCells() }
    val contentRows = rows.filterNot(::isSeparatorRow)
    if (contentRows.isEmpty()) return null

    val separatorIndex = rows.indexOfFirst(::isSeparatorRow)
    val hasHeader = separatorIndex > 0 || (separatorIndex < 0 && contentRows.size >= 2)
    val header = if (hasHeader) contentRows.first() else emptyList()
    val dataRows = if (hasHeader) contentRows.drop(1) else contentRows
    if (header.isEmpty() && dataRows.isEmpty()) return null

    val width = (listOf(header.size) + dataRows.map { it.size }).max()
    fun normalize(cells: List<String>): List<String> =
        List(width) { column -> cells.getOrNull(column).orEmpty() }

    return MarkdownBlock.Table(
        header = if (header.isEmpty()) emptyList() else normalize(header),
        rows = dataRows.map(::normalize),
    )
}

private fun isSeparatorRow(cells: List<String>): Boolean =
    cells.isNotEmpty() && cells.all { it.matches(TABLE_SEPARATOR_CELL) }

private fun MarkdownBlock.Table.previewLine(): String {
    val head = header.filter(String::isNotBlank).joinToString(" · ")
    val body = rows.joinToString("; ") { row ->
        if (row.size <= 2) row.joinToString(" → ") { it.ifBlank { "—" } }
        else row.joinToString(" · ") { it.ifBlank { "—" } }
    }
    return listOf(head, body).filter(String::isNotBlank).joinToString(": ")
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

@Composable
internal fun MarkdownBlockView(block: MarkdownBlock, modifier: Modifier = Modifier) {
    val accent = MaterialTheme.colorScheme.primary
    when (block) {
        is MarkdownBlock.Heading -> Text(
            text = inlineMarkdown(block.text, accent),
            modifier = modifier.fillMaxWidth(),
            style = when (block.level) {
                1 -> MaterialTheme.typography.titleLarge
                2 -> MaterialTheme.typography.titleMedium
                else -> MaterialTheme.typography.titleSmall
            },
        )
        is MarkdownBlock.Paragraph -> Text(
            text = inlineMarkdown(block.text, accent),
            modifier = modifier.fillMaxWidth(),
            style = MaterialTheme.typography.bodyMedium,
        )
        is MarkdownBlock.ListItem -> Text(
            text = buildAnnotatedString {
                pushStyle(SpanStyle(color = accent, fontWeight = FontWeight.Bold))
                append(block.marker)
                pop()
                append("  ")
                append(inlineMarkdown(block.text, accent))
            },
            modifier = modifier.fillMaxWidth(),
            style = MaterialTheme.typography.bodyMedium,
        )
        is MarkdownBlock.Quote -> Box(
            modifier.fillMaxWidth()
                .background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(12.dp))
                .padding(10.dp),
        ) {
            Text(
                inlineMarkdown(block.text, accent),
                color = MaterialTheme.colorScheme.onPrimaryContainer,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        is MarkdownBlock.Code -> Box(
            modifier.fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceContainerLow, RoundedCornerShape(12.dp))
                .padding(10.dp),
        ) {
            Text(
                text = block.text,
                style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
        is MarkdownBlock.Math -> Box(
            modifier.fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceContainerLow, RoundedCornerShape(12.dp))
                .padding(10.dp),
        ) {
            Text(
                // One formula is one flow of text: the parts wrap naturally at the
                // card width instead of being spread out or centred apart.
                text = mathAnnotated(block.source, accent),
                style = MaterialTheme.typography.bodyMedium.copy(
                    fontFamily = FontFamily.Serif,
                    // Every Wear body style sets lineHeight == fontSize, so a
                    // two-line system had no leading and a shifted subscript almost
                    // touched the line below it.
                    lineHeight = MATH_LINE_HEIGHT,
                ),
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        is MarkdownBlock.Table -> TableBlockView(block, modifier, accent)
        MarkdownBlock.Divider -> Box(
            modifier.fillMaxWidth().padding(vertical = 4.dp)
                .background(MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(1.dp)),
        )
    }
}

/**
 * Vertical, container-width table card. Nothing scrolls horizontally: long keys
 * and values wrap, keys are quieter than values, and rows are separated by a
 * hairline instead of a grid.
 */
@Composable
private fun TableBlockView(
    table: MarkdownBlock.Table,
    modifier: Modifier = Modifier,
    accent: Color,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        val header = table.header.filter(String::isNotBlank).joinToString(" · ")
        if (header.isNotBlank()) {
            // Wear M3 labelLarge is 22 sp and labelMedium 18 sp — both larger than
            // the 16 sp body scale, which made the section header read like an H1.
            // The table header stays at body size: only weight and tone separate
            // it from the values, and it may wrap to at most two lines so a long
            // header never inflates the card.
            Text(
                text = header,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 2.dp),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = FontWeight.SemiBold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        table.rows.forEachIndexed { index, row ->
            if (index > 0) {
                Spacer(
                    Modifier.fillMaxWidth().height(1.dp)
                        .background(MaterialTheme.colorScheme.outlineVariant),
                )
            }
            TableRowView(table.header, row, accent)
        }
    }
}

@Composable
private fun TableRowView(header: List<String>, row: List<String>, accent: Color) {
    val title = row.firstOrNull().orEmpty()
    val labelColor = MaterialTheme.colorScheme.onSurfaceVariant
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        if (title.isNotBlank()) {
            // Two-column tables use the first cell as a quiet key; wider tables
            // use it as the record title.
            if (row.size <= 2) {
                Text(
                    text = inlineMarkdown(title, accent),
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                Text(
                    text = inlineMarkdown(title, accent),
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                )
            }
        }
        if (row.size <= 2) {
            val value = row.getOrNull(1).orEmpty().ifBlank { "—" }
            Text(
                text = buildAnnotatedString {
                    pushStyle(SpanStyle(color = accent, fontWeight = FontWeight.Bold))
                    append("→ ")
                    pop()
                    append(inlineMarkdown(value, accent))
                },
                modifier = Modifier.fillMaxWidth(),
                style = MaterialTheme.typography.bodyMedium,
            )
        } else {
            row.drop(1).forEachIndexed { column, cell ->
                val label = header.getOrNull(column + 1).orEmpty()
                Text(
                    text = buildAnnotatedString {
                        if (label.isNotBlank()) {
                            pushStyle(SpanStyle(color = labelColor))
                            append("$label: ")
                            pop()
                        }
                        append(inlineMarkdown(cell.ifBlank { "—" }, accent))
                    },
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Inline spans and TeX
// ---------------------------------------------------------------------------

internal fun inlineMarkdown(source: String, accent: Color = SignalBlue): AnnotatedString = buildAnnotatedString {
    var index = 0
    while (index < source.length) {
        when {
            source.startsWith("**", index) -> {
                val end = source.indexOf("**", index + 2)
                if (end > index + 2) {
                    pushStyle(SpanStyle(fontWeight = FontWeight.Bold))
                    append(source.substring(index + 2, end))
                    pop()
                    index = end + 2
                } else append(source[index++])
            }
            source[index] == '`' -> {
                val end = source.indexOf('`', index + 1)
                if (end > index + 1) {
                    pushStyle(SpanStyle(fontFamily = FontFamily.Monospace, color = accent))
                    append(source.substring(index + 1, end))
                    pop()
                    index = end + 1
                } else append(source[index++])
            }
            source[index] == '$' -> {
                val end = source.indexOf('$', index + 1)
                if (end > index + 1) {
                    pushStyle(SpanStyle(fontFamily = FontFamily.Serif, color = accent))
                    append(mathAnnotated(source.substring(index + 1, end), accent))
                    pop()
                    index = end + 1
                } else append(source[index++])
            }
            source.startsWith("\\(", index) || source.startsWith("\\[", index) -> {
                val closing = if (source[index + 1] == '(') "\\)" else "\\]"
                val end = source.indexOf(closing, index + 2)
                if (end > index + 2) {
                    pushStyle(SpanStyle(fontFamily = FontFamily.Serif, color = accent))
                    append(mathAnnotated(source.substring(index + 2, end), accent))
                    pop()
                    index = end + closing.length
                } else append(source[index++])
            }
            source.startsWith("~~", index) -> {
                val end = source.indexOf("~~", index + 2)
                if (end > index + 2) {
                    pushStyle(SpanStyle(textDecoration = TextDecoration.LineThrough))
                    append(source.substring(index + 2, end))
                    pop()
                    index = end + 2
                } else append(source[index++])
            }
            source[index] == '*' -> {
                val end = source.indexOf('*', index + 1)
                if (end > index + 1) {
                    pushStyle(SpanStyle(fontStyle = FontStyle.Italic))
                    append(source.substring(index + 1, end))
                    pop()
                    index = end + 1
                } else append(source[index++])
            }
            source[index] == '[' -> {
                val labelEnd = source.indexOf(']', index + 1)
                val urlStart = if (labelEnd >= 0 && labelEnd + 1 < source.length && source[labelEnd + 1] == '(') labelEnd + 2 else -1
                val urlEnd = if (urlStart >= 0) source.indexOf(')', urlStart) else -1
                if (labelEnd > index && urlEnd > urlStart) {
                    pushStyle(SpanStyle(color = accent, textDecoration = TextDecoration.Underline))
                    append(source.substring(index + 1, labelEnd))
                    pop()
                    index = urlEnd + 1
                } else append(source[index++])
            }
            // A stray backslash must never reach the reader. Escaped literals lose
            // the backslash; TeX commands are folded through mathDisplay, so
            // `\left(` -> `(`, `\alpha` -> `α` and an unknown `\foo` -> `foo`.
            source[index] == '\\' -> {
                val next = source.getOrNull(index + 1)
                when {
                    next == null -> {
                        append(source[index])
                        index++
                    }
                    next in ESCAPED_LITERALS -> {
                        append(next)
                        index += 2
                    }
                    // TeX line break carries no readable glyph.
                    next == '\\' -> index += 2
                    next.isWhitespace() || next in ",;:!" -> {
                        append(' ')
                        index += 2
                    }
                    else -> {
                        val end = latexRunEnd(source, index)
                        if (end > index + 1) {
                            append(mathAnnotated(source.substring(index, end), accent))
                            index = end
                        } else {
                            append(source[index])
                            index++
                        }
                    }
                }
            }
            else -> append(source[index++])
        }
    }
}

/** End index (exclusive) of a TeX command with its attached `{...}`/`[...]` arguments. */
private fun latexRunEnd(source: String, start: Int): Int {
    var cursor = start + 1
    while (cursor < source.length && source[cursor].isLetter()) cursor += 1
    if (cursor == start + 1) return cursor
    if (source.startsWith("sqrt", start + 1)) {
        if (source.getOrNull(cursor) == '[') {
            val close = source.indexOf(']', cursor + 1)
            if (close > cursor) cursor = close + 1
        }
    }
    while (source.getOrNull(cursor) == '{') {
        val group = source.bracedGroup(cursor) ?: break
        cursor = group.nextIndex
    }
    return cursor
}

/** Converts common TeX notation into a compact, readable Wear OS formula without raw delimiters. */
internal fun mathDisplay(source: String): String = mathAnnotated(source).text

/**
 * A formula as styled text.
 *
 * Short numeric scripts become Unicode (`x^2` -> `x²`, `y_{10}` -> `y₁₀`).
 * Anything longer, or Cyrillic, keeps its own span with a smaller size and a
 * baseline shift: Unicode has no subscript glyphs for `по теч.`, so without this
 * an index either turned into garbage or was flattened into the base line.
 */
internal fun mathAnnotated(source: String, accent: Color = SignalBlue): AnnotatedString =
    buildAnnotatedString { appendMathExpression(compactMathSpacing(source.trim()), accent) }

/**
 * Compacts formula spacing before rendering.
 *
 * TeX's `\quad`/`\qquad` size gaps for a printed page. On a 233 dp round screen
 * they read as two unrelated fragments, and the source usually adds its own
 * spaces around them on top. Both become ordinary spaces and any run of spaces is
 * capped at [MAX_MATH_SPACES], so `, \qquad v` cannot open a hole in the middle of
 * one formula. `\text{…}` keeps the spacing it was written with.
 */
private fun compactMathSpacing(source: String): String {
    val out = StringBuilder()
    var index = 0
    var pendingSpaces = 0

    fun flushSpaces() {
        if (pendingSpaces > 0) {
            out.append(" ".repeat(minOf(pendingSpaces, MAX_MATH_SPACES)))
            pendingSpaces = 0
        }
    }

    while (index < source.length) {
        val char = source[index]
        when {
            char == '\\' -> {
                val end = mathCommandEnd(source, index)
                val name = source.substring(index + 1, minOf(end, source.length))
                when {
                    name == "quad" -> {
                        // A run of spaces is only as wide as its widest member, so
                        // `\quad` plus the source's own spaces stays one space.
                        pendingSpaces = maxOf(pendingSpaces, 1)
                        index = end
                    }
                    name == "qquad" -> {
                        pendingSpaces = maxOf(pendingSpaces, 2)
                        index = end
                    }
                    name in MATH_TEXT_COMMANDS -> {
                        // Literal text keeps its own inner spacing.
                        flushSpaces()
                        val group = source.bracedGroup(end)
                        val stop = group?.nextIndex ?: end
                        out.append(source, index, minOf(stop, source.length))
                        index = stop
                    }
                    else -> {
                        flushSpaces()
                        out.append(source, index, minOf(end, source.length))
                        index = end
                    }
                }
            }
            char == ' ' -> {
                pendingSpaces = maxOf(pendingSpaces, 1)
                index += 1
            }
            char == '\n' -> {
                pendingSpaces = 0
                out.append('\n')
                index += 1
            }
            else -> {
                flushSpaces()
                out.append(char)
                index += 1
            }
        }
    }
    flushSpaces()
    return out.toString().trim()
}

/** Index just after the command that starts at [start] (`\frac`, `\,`, `\%`…). */
private fun mathCommandEnd(source: String, start: Int): Int {
    var end = start + 1
    if (end < source.length && source[end].isLetter()) {
        while (end < source.length && source[end].isLetter()) end += 1
    } else {
        end += 1
    }
    return minOf(end, source.length)
}

private fun AnnotatedString.Builder.appendMathExpression(source: String, accent: Color) {
    var index = 0
    while (index < source.length) {
        when (val char = source[index]) {
            '\\' -> index = appendMathCommand(source, index, accent)
            '^', '_' -> index = appendMathScript(source, index, char == '^', accent)
            // Grouping braces are structure, not text.
            '{', '}' -> index += 1
            else -> {
                append(char)
                index += 1
            }
        }
    }
}

/** Renders one `\command` and returns the index after it. */
private fun AnnotatedString.Builder.appendMathCommand(source: String, start: Int, accent: Color): Int {
    val next = source.getOrNull(start + 1) ?: run {
        append('\\')
        return start + 1
    }
    if (next in ESCAPED_LITERALS) {
        append(next)
        return start + 2
    }
    if (next == '\\') {
        // TeX line break inside a formula.
        append('\n')
        return start + 2
    }
    if (next.isWhitespace() || next in ",;:!") {
        append(' ')
        return start + 2
    }
    // Read the whole command name at once. Substring replacements used to mangle
    // commands that merely start with another one (`\rightarrow` vs `\right`).
    var end = start + 1
    while (end < source.length && source[end].isLetter()) end += 1
    if (end == start + 1) {
        append(next)
        return start + 2
    }
    val name = source.substring(start + 1, end)
    return when {
        name == "frac" -> appendMathFraction(source, end, accent)
        name == "sqrt" -> appendMathRoot(source, end, accent)
        name == "quad" -> {
            append(' ')
            end
        }
        name == "qquad" -> {
            append("  ")
            end
        }
        // `\text{…}` and friends are literal text: keep their spacing as written.
        name in MATH_TEXT_COMMANDS -> {
            val group = source.bracedGroup(end)
            if (group == null) {
                append(name)
                end
            } else {
                append(group.value)
                group.nextIndex
            }
        }
        name in MATH_INVISIBLE_COMMANDS -> end
        else -> {
            append(MATH_SYMBOLS[name] ?: name)
            end
        }
    }
}

private fun AnnotatedString.Builder.appendMathFraction(source: String, nameEnd: Int, accent: Color): Int {
    val numerator = source.bracedGroup(nameEnd)
    val denominator = numerator?.let { source.bracedGroup(it.nextIndex) }
    if (numerator == null || denominator == null) {
        append("frac")
        return nameEnd
    }
    val topParens = needsFractionParens(numerator.value)
    val bottomParens = needsFractionParens(denominator.value)
    if (topParens) append('(')
    appendMathExpression(numerator.value, accent)
    if (topParens) append(')')
    append('⁄')
    if (bottomParens) append('(')
    appendMathExpression(denominator.value, accent)
    if (bottomParens) append(')')
    return denominator.nextIndex
}

private fun needsFractionParens(value: String): Boolean =
    value.any { it.isWhitespace() || it in "+−-" }

private fun AnnotatedString.Builder.appendMathRoot(source: String, nameEnd: Int, accent: Color): Int {
    val group = source.bracedGroup(nameEnd)
    if (group == null) {
        append('√')
        return nameEnd
    }
    append("√(")
    appendMathExpression(group.value, accent)
    append(')')
    return group.nextIndex
}

/** `x_1`/`x^2` (Unicode when numeric) or a real shifted span for longer content. */
private fun AnnotatedString.Builder.appendMathScript(
    source: String,
    start: Int,
    superscript: Boolean,
    accent: Color,
): Int {
    val group = source.bracedGroup(start + 1)
    val argument: String
    var next: Int
    if (group != null) {
        argument = group.value
        next = group.nextIndex
    } else {
        val single = source.getOrNull(start + 1) ?: run {
            append(if (superscript) '^' else '_')
            return start + 1
        }
        if (single == '\\') {
            // `^\circ`: the argument is the whole command, not just its backslash.
            var end = start + 2
            while (end < source.length && source[end].isLetter()) end += 1
            argument = source.substring(start + 1, end)
            next = end
        } else {
            argument = single.toString()
            next = start + 2
        }
    }
    if (argument == "\\circ") {
        append('°')
        // `^\circ C` reads as `°C`.
        if (source.getOrNull(next) == ' ') next += 1
        return next
    }
    val plain = mathDisplay(argument)
    if (plain.isNotEmpty() && plain.all { it in "0123456789+-" }) {
        append(if (superscript) superscript(plain) else subscript(plain))
        return next
    }
    pushStyle(
        SpanStyle(
            fontSize = SCRIPT_FONT_SCALE,
            baselineShift = if (superscript) SUPERSCRIPT_SHIFT else SUBSCRIPT_SHIFT,
        ),
    )
    appendMathExpression(argument, accent)
    pop()
    return next
}

/** TeX commands the watch can draw as a single glyph. */
private val MATH_SYMBOLS = mapOf(
    "times" to "×", "cdot" to "·", "pm" to "±", "mp" to "∓",
    "leq" to "≤", "le" to "≤", "geq" to "≥", "ge" to "≥",
    "neq" to "≠", "ne" to "≠", "approx" to "≈", "equiv" to "≡",
    "Rightarrow" to "⇒", "Leftarrow" to "⇐", "Leftrightarrow" to "⇔",
    "rightarrow" to "→", "leftarrow" to "←", "leftrightarrow" to "↔",
    "implies" to "⇒", "iff" to "⇔", "to" to "→", "mapsto" to "↦",
    "infty" to "∞", "circ" to "°", "degree" to "°",
    "sum" to "Σ", "prod" to "∏", "int" to "∫", "partial" to "∂", "nabla" to "∇",
    "pi" to "π", "theta" to "θ", "alpha" to "α", "beta" to "β", "gamma" to "γ",
    "delta" to "δ", "epsilon" to "ε", "varepsilon" to "ε", "zeta" to "ζ", "eta" to "η",
    "kappa" to "κ", "lambda" to "λ", "mu" to "μ", "nu" to "ν", "xi" to "ξ",
    "rho" to "ρ", "sigma" to "σ", "tau" to "τ", "phi" to "φ", "varphi" to "φ",
    "chi" to "χ", "psi" to "ψ", "omega" to "ω",
    "Delta" to "Δ", "Gamma" to "Γ", "Theta" to "Θ", "Lambda" to "Λ", "Xi" to "Ξ",
    "Pi" to "Π", "Sigma" to "Σ", "Phi" to "Φ", "Psi" to "Ψ", "Omega" to "Ω",
    "ldots" to "…", "dots" to "…", "cdots" to "⋯",
    "angle" to "∠", "perp" to "⊥", "parallel" to "∥", "in" to "∈", "notin" to "∉",
    "subset" to "⊂", "supset" to "⊃", "cup" to "∪", "cap" to "∩", "emptyset" to "∅",
    "forall" to "∀", "exists" to "∃", "neg" to "¬", "land" to "∧", "lor" to "∨",
    "propto" to "∝", "sim" to "∼", "cong" to "≅", "ll" to "≪", "gg" to "≫",
)

private val MATH_TEXT_COMMANDS = setOf(
    "text", "mathrm", "mathit", "mathbf", "mathsf", "mathtt",
    "mathcal", "mathbb", "mathfrak", "operatorname",
)

/** Commands that only steer layout and must not print their own name. */
private val MATH_INVISIBLE_COMMANDS = setOf(
    "left", "right", "big", "Big", "bigg", "Bigg",
    "displaystyle", "textstyle", "scriptstyle", "limits", "nolimits",
)

private val SCRIPT_FONT_SCALE = 0.75.em

/**
 * Compose's [BaselineShift.Subscript] is ±0.5 of the *span's* size. At a 0.75 em
 * script on a 16 sp line that drops the glyph about 6 sp below the baseline, while
 * the line only reserves a few sp underneath — a Cyrillic index such as `x_{теч}`
 * then overlapped the next line of the same formula. A softer shift still reads as
 * a script and stays inside the line box.
 */
private val SUBSCRIPT_SHIFT = BaselineShift(-0.3f)
private val SUPERSCRIPT_SHIFT = BaselineShift(0.3f)

/**
 * Leading for a formula block. The Wear type scale sets lineHeight equal to the
 * font size; a multi-line formula needs a little more, both between its own lines
 * and around a baseline-shifted subscript.
 */
private val MATH_LINE_HEIGHT = 1.35.em

/**
 * Largest run of spaces allowed inside a formula. `\qquad` plus the source's own
 * spaces must not turn one expression into two distant blocks.
 */
private const val MAX_MATH_SPACES = 2

private data class BracedGroup(val value: String, val nextIndex: Int)

private fun String.bracedGroup(openIndex: Int): BracedGroup? {
    if (getOrNull(openIndex) != '{') return null
    var depth = 0
    for (index in openIndex until length) when (this[index]) {
        '{' -> depth += 1
        '}' -> { depth -= 1; if (depth == 0) return BracedGroup(substring(openIndex + 1, index), index + 1) }
    }
    return null
}

private fun superscript(value: String): String = value.map { "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻".getOrNull("0123456789+-".indexOf(it)) ?: it }.joinToString("")
private fun subscript(value: String): String = value.map { "₀₁₂₃₄₅₆₇₈₉₊₋".getOrNull("0123456789+-".indexOf(it)) ?: it }.joinToString("")
