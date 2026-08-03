import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { purgeStaleClientCaches } from './utils/purgeStaleClientCaches'
import './style.css'

void purgeStaleClientCaches()

createApp(App).use(createPinia()).use(router).mount('#app')
