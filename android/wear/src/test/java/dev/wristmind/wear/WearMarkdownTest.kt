package dev.wristmind.wear

import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WearMarkdownTest {
    @Test
    fun parsesReadableBlocksForSingleScrollableAnswer() {
        val blocks = parseMarkdown(
            """
            # Ответ

            Короткий **текст**.
            - Первый пункт
            2. Второй пункт
            > Важно
            ```kotlin
            val ready = true
            ```
            """.trimIndent(),
        )

        assertEquals(MarkdownBlock.Heading(1, "Ответ"), blocks[0])
        assertTrue(blocks[1] is MarkdownBlock.Paragraph)
        assertEquals(MarkdownBlock.ListItem("•", "Первый пункт"), blocks[2])
        assertEquals(MarkdownBlock.ListItem("2.", "Второй пункт"), blocks[3])
        assertEquals(MarkdownBlock.Quote("Важно"), blocks[4])
        assertEquals(MarkdownBlock.Code("val ready = true"), blocks[5])
    }

    @Test
    fun unclosedCodeBlockIsNotLost() {
        assertEquals(
            listOf(MarkdownBlock.Code("answer")),
            parseMarkdown("```\nanswer"),
        )
    }

    @Test
    fun rendersInlineAndBlockMathWithoutRawTexDelimiters() {
        assertEquals("x² + y₁ = 5", mathDisplay("x^2 + y_1 = 5"))
        assertEquals("a⁄b × √(4)", mathDisplay("\\frac{a}{b} \\times \\sqrt{4}"))
        assertEquals("x¹² + y₁₀", mathDisplay("x^{12} + y_{10}"))
        assertEquals("λ = 3,4 · 10⁵ Дж/(кг·°C)", mathDisplay("\\lambda = 3,4 \\cdot 10^5 Дж/(кг\\cdot^\\circ C)"))
        assertEquals(listOf(MarkdownBlock.Math("E = mc^2")), parseMarkdown("$$\nE = mc^2\n$$"))
    }

    @Test
    fun rendersLatexParenthesisDelimitersAndCdotFromAssistantAnswers() {
        assertEquals(
            "Q = 230 · 2 · 290 = 133400 Дж.",
            inlineMarkdown("\\( Q = 230 \\cdot 2 \\cdot 290 = 133400 \\) Дж.").text,
        )
        assertEquals("F = ma", inlineMarkdown("\\[ F = ma \\]").text)
    }

    // --- Tables -----------------------------------------------------------------

    /** A. Normal two-column table becomes vertical key/value pairs, never raw `|`. */
    @Test
    fun twoColumnTableBecomesVerticalPairs() {
        val source = """
            | Параметр | Значение |
            |---|---|
            | Android | 16 |
            | Python | 3.14 |
        """.trimIndent()
        val blocks = parseMarkdown(source)
        val table = blocks.filterIsInstance<MarkdownBlock.Table>().single()

        assertEquals(listOf("Параметр", "Значение"), table.header)
        assertEquals(listOf(listOf("Android", "16"), listOf("Python", "3.14")), table.rows)
        assertFalse(previewMarkdown(source).text.contains("|"))
        assertEquals(
            "Параметр · Значение: Android → 16; Python → 3.14",
            previewMarkdown(source).text,
        )
    }

    /** B. Three columns: first column is the record title, the rest are labelled fields. */
    @Test
    fun threeColumnTableKeepsFirstColumnAsTitle() {
        val source = """
            | Модель | Цена | Скорость |
            |---|---|---|
            | A | 10 | Fast |
        """.trimIndent()
        val table = parseMarkdown(source).filterIsInstance<MarkdownBlock.Table>().single()

        assertEquals(listOf("Модель", "Цена", "Скорость"), table.header)
        assertEquals(listOf(listOf("A", "10", "Fast")), table.rows)
        assertEquals(
            "Модель · Цена · Скорость: A · 10 · Fast",
            previewMarkdown(source).text,
        )
    }

    /** C. A table with a single data row is still a table. */
    @Test
    fun singleDataRowTableIsStructured() {
        val table = parseMarkdown(
            """
            | Параметр | Значение |
            |---|---|
            | Android | 16 |
            """.trimIndent(),
        ).filterIsInstance<MarkdownBlock.Table>().single()

        assertEquals(listOf("Параметр", "Значение"), table.header)
        assertEquals(listOf(listOf("Android", "16")), table.rows)
    }

    /** D. No separator row, no trailing pipe, loose spacing, empty cells. */
    @Test
    fun tableWithoutSeparatorRowOrTrailingPipeIsStillNormalized() {
        val table = parseMarkdown(
            """
            | Параметр | Значение
            | Android | 16
            """.trimIndent(),
        ).filterIsInstance<MarkdownBlock.Table>().single()

        assertEquals(listOf("Параметр", "Значение"), table.header)
        assertEquals(listOf(listOf("Android", "16")), table.rows)

        val loose = parseMarkdown(
            """
            | A |   | C |
            | 1 | 2 | 3 |
            """.trimIndent(),
        ).filterIsInstance<MarkdownBlock.Table>().single()

        assertEquals(listOf("A", "", "C"), loose.header)
        assertEquals(listOf(listOf("1", "2", "3")), loose.rows)
    }

    @Test
    fun singleLineTableIsNotLeftRaw() {
        val source = "| Параметр | Значение |"
        val table = parseMarkdown(source).filterIsInstance<MarkdownBlock.Table>().single()

        assertTrue(table.header.isEmpty())
        assertEquals(listOf(listOf("Параметр", "Значение")), table.rows)
        assertFalse(previewMarkdown(source).text.contains("|"))
    }

    /** E. A table inside a fenced code block stays verbatim. */
    @Test
    fun tableInsideCodeBlockIsUntouched() {
        val source = "```\n| A | B |\n|---|---|\n| 1 | 2 |\n```"
        val blocks = parseMarkdown(source)

        assertEquals(1, blocks.size)
        assertEquals(MarkdownBlock.Code("| A | B |\n|---|---|\n| 1 | 2 |"), blocks[0])
        assertTrue(blocks.none { it is MarkdownBlock.Table })
    }

    // --- Feed preview -----------------------------------------------------------

    /** F. Assistant preview loses raw Markdown markers, keeps link labels and math. */
    @Test
    fun assistantPreviewHasNoRawMarkdownMarkers() {
        val preview = previewMarkdown("**жирный**, [ссылка](https://example.org), \$x^2\$")

        assertEquals("жирный, ссылка, x²", preview.text)
        assertTrue(preview.spanStyles.any { it.item.fontWeight == FontWeight.Bold })
        assertFalse(preview.text.contains("**"))
        assertFalse(preview.text.contains("https://"))
    }

    @Test
    fun assistantPreviewFlattensHeadingsListsAndTables() {
        val preview = previewMarkdown(
            """
            # Ответ

            - Первый пункт

            | Параметр | Значение |
            |---|---|
            | Android | 16 |
            """.trimIndent(),
        ).text

        assertFalse(preview.contains("#"))
        assertFalse(preview.contains("|"))
        assertTrue(preview.contains("Первый пункт"))
        assertTrue(preview.contains("Android → 16"))
    }

    /** G. A blank answer yields no blocks at all, so no empty card is rendered. */
    @Test
    fun emptyAnswerProducesNoBlocks() {
        assertTrue(parseMarkdown("").isEmpty())
        assertTrue(parseMarkdown("   \n\n  ").isEmpty())
        assertEquals("", previewPlainText("   \n "))
    }

    /** H. Unknown/control TeX never leaves visible backslash garbage. */
    @Test
    fun texControlCommandsAndEscapesDoNotProduceGarbage() {
        assertEquals("( x )", mathDisplay("\\left( x \\right)"))
        assertEquals("( x )", inlineMarkdown("\\left( x \\right)").text)
        assertFalse(inlineMarkdown("\\left( x \\right)").text.contains("left"))

        assertEquals("50%", mathDisplay("50\\%"))
        assertEquals("цена 50%", inlineMarkdown("цена 50\\%").text)

        // Unknown commands degrade to their readable name instead of a backslash.
        assertEquals("foo", mathDisplay("\\foo"))
        assertEquals("α", inlineMarkdown("\\alpha").text)
    }

    // --- Server source section --------------------------------------------------

    @Test
    fun hidesServerSearchSourceSectionOnTheWatch() {
        assertEquals(
            "Короткий ответ.",
            withoutSearchSources("Короткий ответ.\n\n**Источники поиска**\n- [Источник](https://example.org)"),
        )
        assertEquals(
            "Короткий ответ.",
            withoutSearchSources("Короткий ответ.\n\n**Источники**\n- [Источник](https://example.org)"),
        )
        assertEquals(
            "Короткий ответ.",
            withoutSearchSources("Короткий ответ.\n\n**Использованные источники**\n- [Источник](https://example.org)"),
        )
        // The server section is emitted in upper case by some models.
        assertEquals(
            "Короткий ответ.",
            withoutSearchSources("Короткий ответ.\n\n**ИСПОЛЬЗОВАННЫЕ ИСТОЧНИКИ**\n- [A](https://example.org)"),
        )
    }

    /**
     * Regression: the old regex matched *any* standalone bold line containing
     * "источник", so a real reference line such as `**Источник**` truncated the
     * rest of the answer — or erased all of it when it came first.
     */
    @Test
    fun keepsASingularSourceReferenceInsideTheAnswer() {
        val leading = "**Источник**\n\nОсновной ответ: 5."
        assertEquals(leading, withoutSearchSources(leading))

        val inline = "План.\n\n**Источник:** учебник, с. 42\n\nВывод: 5."
        assertEquals(inline, withoutSearchSources(inline))

        val midAnswer = "Начало.\n\n**Источник**\n\nПродолжение ответа."
        assertEquals(midAnswer, withoutSearchSources(midAnswer))
    }

    @Test
    fun onlyRealServerSectionsAreRemoved() {
        // The in-answer reference line stays; only the server's own trailing
        // section is hidden.
        assertEquals(
            "Тело.\n\n**Источник:** с. 42",
            withoutSearchSources(
                "Тело.\n\n**Источник:** с. 42\n\n**Использованные источники**\n- [A](https://a)",
            ),
        )
    }

    @Test
    fun rendersNestedFractionTextAndApproximation() {
        assertEquals("F = (Pгруза + Pблока)⁄(2 η)", mathDisplay("F = \\frac{P_{\\text{груза}} + P_{\\text{блока}}}{2 \\eta}"))
        assertEquals("mg ≈ 10 Н/кг", mathDisplay("mg \\approx 10 Н/кг"))
    }

    // --- Formulas ---------------------------------------------------------------

    @Test
    fun rendersArrowsAndSpacingCommands() {
        assertEquals("A ⇒ B", mathDisplay("A \\Rightarrow B"))
        assertEquals("A ⇐ B", mathDisplay("A \\Leftarrow B"))
        assertEquals("A → B", mathDisplay("A \\rightarrow B"))
        assertEquals("A ← B", mathDisplay("A \\leftarrow B"))
        assertEquals("a b", mathDisplay("a\\quad b"))
        assertEquals("a  b", mathDisplay("a\\qquad b"))
        assertEquals("2 · 3 × 4 ± 5", mathDisplay("2 \\cdot 3 \\times 4 \\pm 5"))
        assertEquals("x ≤ 5 ≥ y", mathDisplay("x \\leq 5 \\geq y"))
    }

    @Test
    fun aCommandIsNeverMangledByAnotherCommandPrefix() {
        // `\rightarrow` used to lose its head to the `\right` control command.
        assertEquals("→", mathDisplay("\\rightarrow"))
        assertEquals("⇒", mathDisplay("\\Rightarrow"))
        assertEquals("( x )", mathDisplay("\\left( x \\right)"))
    }

    @Test
    fun shortNumericScriptsBecomeUnicode() {
        assertEquals("x₁ + x₂ = x²", mathDisplay("x_1 + x_2 = x^2"))
        assertEquals("x¹² + y₁₀", mathDisplay("x^{12} + y_{10}"))
        assertEquals(0, mathAnnotated("x_1").spanStyles.size)
    }

    @Test
    fun longOrCyrillicScriptsKeepAShiftedSpan() {
        val subscript = mathAnnotated("v_{по теч.}")
        assertEquals("vпо теч.", subscript.text)
        val subscriptShift = subscript.spanStyles.mapNotNull { it.item.baselineShift }.firstOrNull()
        assertNotNull(subscriptShift)
        assertTrue("subscript must sit below the baseline", (subscriptShift?.multiplier ?: 0f) < 0f)
        assertTrue(subscript.spanStyles.any { it.item.fontSize == 0.75.em })

        val cyrillic = mathAnnotated("x_{теч}")
        assertEquals("xтеч", cyrillic.text)
        assertTrue(cyrillic.spanStyles.any { (it.item.baselineShift?.multiplier ?: 0f) < 0f })

        val compound = mathAnnotated("a^{n+1}")
        assertEquals("an+1", compound.text)
        assertTrue(compound.spanStyles.any { (it.item.baselineShift?.multiplier ?: 0f) > 0f })
    }

    /**
     * Regression: the default ±0.5 shift pushed a 0.75 em script outside the line
     * box, so `x_{теч}` overlapped the line below it inside the same formula.
     */
    @Test
    fun aScriptShiftStaysInsideTheLineBox() {
        val shifts = mathAnnotated("x_{теч} = 2\nv_{по теч.} = x + 2")
            .spanStyles
            .mapNotNull { it.item.baselineShift?.multiplier }

        assertTrue(shifts.isNotEmpty())
        assertTrue("shift must be softer than Compose's 0.5", shifts.all { abs(it) < 0.5f })
        assertTrue("shift must still be visible", shifts.all { abs(it) >= 0.2f })
    }

    @Test
    fun textCommandContentStaysReadable() {
        assertEquals("x = 9 или x = -9", mathDisplay("x = 9\\text{ или }x = -9"))
        assertEquals("скорость по теч.", mathDisplay("\\text{скорость по теч.}"))
    }

    @Test
    fun displayMathBecomesOneBlockWithoutDelimiters() {
        val block = parseMarkdown("\\[\nx=9\\text{ или }x=-9\n\\]")

        assertEquals(1, block.size)
        val math = block[0] as MarkdownBlock.Math
        assertEquals("x=9\\text{ или }x=-9", math.source)
        assertEquals("x=9 или x=-9", mathDisplay(math.source))
    }

    @Test
    fun displayMathKeepsItsLineBreaks() {
        val math = parseMarkdown("$$\nx=1\nx=2\n$$").single() as MarkdownBlock.Math
        assertEquals("x=1\nx=2", math.source)

        val bracket = parseMarkdown("\\[\na = b\nc = d\n\\]").single() as MarkdownBlock.Math
        assertEquals("a = b\nc = d", bracket.source)
    }

    @Test
    fun singleLineDisplayMathWorksForBothFences() {
        assertEquals(listOf(MarkdownBlock.Math("x=9")), parseMarkdown("\\[x=9\\]"))
        assertEquals(listOf(MarkdownBlock.Math("E = mc^2")), parseMarkdown("\$\$E = mc^2\$\$"))
    }

    /**
     * Regression: `\quad`/`\qquad` used to render em spaces, so a formula with the
     * source's own spaces around them opened a hole and the two halves read as
     * separate blocks on a round screen. No fixed wide gap may survive.
     */
    @Test
    fun spacingCommandsNeverOpenAFixedGap() {
        assertFalse(mathDisplay("x\\quad y").contains('\u2003'))
        assertFalse(mathDisplay("x\\qquad y").contains('\u2003'))
        assertEquals("a b", mathDisplay("a\\quad b"))
        assertEquals("a  b", mathDisplay("a\\qquad b"))
        // The source's own spaces collapse into the same small run.
        assertEquals("a  b", mathDisplay("a \\qquad b"))
        assertTrue(mathDisplay("a \\qquad b").length <= "a  b".length)
    }

    /** Both halves of a `\qquad`-separated formula stay in one flow of text. */
    @Test
    fun aLongSubscriptKeepsTheFormulaInOneFlow() {
        val rendered = mathDisplay("x_{теч} = 2 км/ч, \\qquad v_{по теч.} = x + 2")

        assertFalse(rendered.contains('\n'))
        assertFalse(rendered.contains('\u2003'))
        assertTrue(rendered.startsWith("xтеч = 2 км/ч,"))
        assertTrue(rendered.endsWith("vпо теч. = x + 2"))
        // At most two spaces between the halves: never a stretched-out line.
        val gap = rendered.removePrefix("xтеч = 2 км/ч,").takeWhile { it == ' ' }
        assertTrue(gap.length <= 2)

        val segments = mathDisplay("\\sqrt{x+4} = x-2, \\qquad \\frac{a}{b}\\cdot\\frac{c}{d}=\\frac{ac}{bd}")
        assertFalse(segments.contains('\u2003'))
        assertTrue(segments.startsWith("√(x+4) = x-2,"))
        assertTrue(segments.endsWith("a⁄b·c⁄d=ac⁄bd"))
    }
}
