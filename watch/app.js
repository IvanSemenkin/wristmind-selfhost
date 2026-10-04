import { BaseApp } from '@zeppos/zml/base-app'
import { log } from '@zos/utils'

const logger = log.getLogger('wristmind-app')

App(
  BaseApp({
    globalData: {},
    onCreate() {
      logger.log('WristMind Side created')
    },
    onDestroy() {
      logger.log('WristMind Side destroyed')
    },
  }),
)
