const path = require('path')
const { spawnSync } = require('child_process')

const root = path.resolve(__dirname, '..')
const cli = require.resolve('@zeppos/zeus-cli/bin/main.js')
const privateModules = path.join(
  root,
  'node_modules',
  '@zeppos',
  'zeus-cli',
  'private-modules',
)
const nodePath = [privateModules, process.env.NODE_PATH].filter(Boolean).join(path.delimiter)
const args = process.argv.slice(2)
if (args[0] === 'build' || args[0] === 'preview') {
  require(path.join(__dirname, 'generate-private-config.cjs'))
}
const preload = process.env.WRISTMIND_QR_PAYLOAD_FILE
  ? ['--require', path.join(__dirname, 'capture-qr.cjs')]
  : []
const result = spawnSync(process.execPath, [...preload, cli, ...args], {
  cwd: root,
  env: { ...process.env, NODE_PATH: nodePath },
  stdio: 'inherit',
})

process.exit(result.status === null ? 1 : result.status)
