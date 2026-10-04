const fs = require('fs')
const path = require('path')

const watchRoot = path.resolve(__dirname, '..')
const propertiesPath = path.resolve(watchRoot, '..', 'android', 'local.properties')
const outputPath = path.join(watchRoot, 'app-side', 'private-config.js')

function readProperties(source) {
  const result = {}
  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const separator = line.indexOf('=')
    if (separator < 0) continue
    const key = line.slice(0, separator).trim()
    const value = line
      .slice(separator + 1)
      .trim()
      .replace(/\\:/g, ':')
      .replace(/\\\\/g, '\\')
    result[key] = value
  }
  return result
}

if (!fs.existsSync(propertiesPath)) {
  throw new Error('android/local.properties is required for the Side Service build')
}

const properties = readProperties(fs.readFileSync(propertiesPath, 'utf8'))
const baseUrl = properties['wristmind.baseUrl']
const apiToken = properties['wristmind.apiToken']
if (!baseUrl || !apiToken) {
  throw new Error('wristmind.baseUrl and wristmind.apiToken are required')
}

fs.writeFileSync(
  outputPath,
  `export const API_BASE_URL = ${JSON.stringify(baseUrl)}\n` +
    `export const API_TOKEN = ${JSON.stringify(apiToken)}\n`,
  { encoding: 'utf8', mode: 0o600 },
)
