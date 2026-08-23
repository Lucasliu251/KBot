/// <reference types="vite/client" />
/// <reference types="vue/macros-global" />

declare global {
  interface Window {
    APP_BASE?: string
    MUSIC_CONSOLE_ASSET_BASE?: string
    INITIAL_CHANNEL_ID?: string
  }
}

export {}
