<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { UserRound } from '@lucide/vue'

const props = defineProps<{ src?: string; name?: string }>()
const failed = ref(false)
const url = computed(() => {
  const raw = props.src?.trim() || ''
  if (raw.startsWith('//')) return `https:${raw}`
  return /^https?:\/\//i.test(raw) ? raw.replace(/^http:/i, 'https:') : ''
})
watch(url, () => { failed.value = false })
</script>

<template>
  <span class="user-avatar" :title="name" role="img" :aria-label="name ? `${name}的头像` : '用户头像'">
    <img v-if="url && !failed" :key="url" :src="url" alt="" referrerpolicy="no-referrer" @error="failed = true" />
    <UserRound v-else :size="12" aria-hidden="true" />
  </span>
</template>

<style scoped>
.user-avatar { width: var(--avatar-size, 22px); height: var(--avatar-size, 22px); flex: 0 0 var(--avatar-size, 22px); display: inline-flex; align-items: center; justify-content: center; overflow: hidden; border-radius: 50%; color: #aaa79f; background: #30302d; }
.user-avatar img { display: block; width: 100%; height: 100%; object-fit: cover; }
</style>
