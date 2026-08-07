import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { purgeStaleClientCaches } from './utils/purgeStaleClientCaches'
import { initPwaInstallCapture } from './utils/pwa'
import { isPushEnabled, prepareNotifyServiceWorker } from './utils/notify'
import './style.css'

void purgeStaleClientCaches()
initPwaInstallCapture()
if (isPushEnabled()) void prepareNotifyServiceWorker()

createApp(App).use(createPinia()).use(router).mount('#app')
