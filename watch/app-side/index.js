import { BaseSideService } from '@zeppos/zml/base-side'
import { API_BASE_URL, API_TOKEN } from './private-config'

const SIDE_SERVICE_BUILD = '0.7.7'

function parseBody(response) {
  return typeof response.body === 'string'
    ? JSON.parse(response.body)
    : response.body
}

async function api(path, method = 'GET', body = null) {
  const response = await fetch({
    url: `${API_BASE_URL.replace(/\/$/, '')}${path}`,
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-WristMind-Token': API_TOKEN,
    },
    body: body === null ? undefined : JSON.stringify(body),
  })
  return parseBody(response)
}

AppSideService(
  BaseSideService({
    onInit() {
      console.log(`WristMind Side Service ${SIDE_SERVICE_BUILD} ready`)
    },

    onRequest(request, response) {
      if (request.method === 'PING') {
        response(null, {
          result: {
            channel: 'ZEPP_SIDE_SERVICE',
            build: SIDE_SERVICE_BUILD,
            receivedAt: Date.now(),
            sentAt: request.params && request.params.sentAt,
          },
        })
        return
      }
      if (request.method === 'COMMAND') {
        api('/v1/bridge/command', 'POST', request.params)
          .then((result) => response(null, { result }))
          .catch((error) => response(error))
        return
      }
      if (request.method === 'STATE') {
        api('/v1/bridge/state')
          .then((result) => response(null, { result }))
          .catch((error) => response(error))
        return
      }
      response(new Error(`Unknown request: ${request.method}`))
    },

    onRun() {},
    onDestroy() {},
  }),
)
