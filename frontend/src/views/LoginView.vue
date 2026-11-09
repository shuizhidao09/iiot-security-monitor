<template>
  <main class="login-shell">
    <section class="login-card">
      <p class="login-eyebrow">IIoT Security Monitor</p>
      <h1>System Login</h1>
      <p class="login-subtitle">Sign in to view device status and telemetry history.</p>

      <el-form label-position="top" @submit.prevent="submitLogin">
        <el-form-item label="Username">
          <el-input v-model="form.username" autocomplete="username" placeholder="Enter username" />
        </el-form-item>
        <el-form-item label="Password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="Enter password"
            @keyup.enter="submitLogin"
          />
        </el-form-item>
        <el-button class="login-button" type="primary" :loading="loading" @click="submitLogin">
          Login
        </el-button>
      </el-form>
    </section>
  </main>
</template>

<script setup>
import { reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";

import { useAuthStore } from "../stores/auth";

const router = useRouter();
const auth = useAuthStore();
const loading = ref(false);
const form = reactive({
  username: "",
  password: ""
});

async function submitLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning("Please enter username and password.");
    return;
  }

  loading.value = true;
  try {
    await auth.login(form);
    ElMessage.success("Login successful.");
    await router.replace({ name: "dashboard" });
  } catch (error) {
    ElMessage.error(error.response?.data?.detail ?? "Login failed.");
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(18, 210, 183, 0.18), transparent 32%),
    radial-gradient(circle at bottom right, rgba(255, 180, 74, 0.14), transparent 30%),
    linear-gradient(135deg, #081019 0%, #101922 52%, #131a20 100%);
}

.login-card {
  width: min(420px, 100%);
  padding: 34px;
  border: 1px solid rgba(154, 174, 186, 0.2);
  border-radius: 14px;
  background: rgba(8, 18, 27, 0.9);
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.28);
}

.login-eyebrow {
  margin: 0 0 10px;
  color: #12d2b7;
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 32px;
}

.login-subtitle {
  color: #96a9b5;
  font-size: 13px;
  margin: 10px 0 26px;
}

.login-button {
  width: 100%;
  margin-top: 8px;
}
</style>
