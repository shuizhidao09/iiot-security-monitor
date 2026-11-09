<template>
  <section class="panel">
    <header class="panel-header">
      <div>
        <p class="panel-eyebrow">{{ eyebrow }}</p>
        <h3 class="panel-title">{{ title }}</h3>
      </div>
      <slot name="action" />
    </header>
    <div class="panel-body">
      <slot />
    </div>
  </section>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    required: true
  },
  eyebrow: {
    type: String,
    default: ""
  }
});
</script>
