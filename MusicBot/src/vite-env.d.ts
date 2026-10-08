/// <reference types="vite/client" />
/// <reference types="vue/macros-global" />

declare global {
  interface Window {
    APP_BASE?: string
    MUSIC_CONSOLE_ASSET_BASE?: string
    INITIAL_CHANNEL_ID?: string
    TRASHBOX_CSRF_TOKEN?: string
  }
}

export {}
