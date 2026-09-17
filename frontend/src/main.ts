import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { purgeStaleClientCaches } from './utils/purgeStaleClientCaches'
import { initPwaInstallCapture } from './utils/pwa'
import { finishLaunchSplash } from './utils/launchSplash'
import { isPushEnabled, prepareNotifyServiceWorker } from './utils/notify'
import './style.css'

void purgeStaleClientCaches()
initPwaInstallCapture()
if (isPushEnabled()) void prepareNotifyServiceWorker()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

void router.isReady().then(() => finishLaunchSplash())