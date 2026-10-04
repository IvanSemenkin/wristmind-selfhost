const fs = require('fs')
const qr = require('qrcode-terminal')

const generate = qr.generate.bind(qr)
qr.generate = (payload, options, callback) => {
  const output = process.env.WRISTMIND_QR_PAYLOAD_FILE
  if (output) {
    fs.writeFileSync(output, payload, 'utf8')
  }
  return generate(payload, options, callback)
}
