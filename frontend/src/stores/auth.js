import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { loginRequest } from "../services/api";

const TOKEN_KEY = "iiot_admin_token";
const USERNAME_KEY = "iiot_admin_username";

export const useAuthStore = defineStore("auth", () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) ?? "");
  const username = ref(localStorage.getItem(USERNAME_KEY) ?? "");

  const isAuthenticated = computed(() => Boolean(token.value));

  async function login(credentials) {
    const result = await loginRequest(credentials);
    token.value = result.token;
    username.value = result.username ?? credentials.username;
    localStorage.setItem(TOKEN_KEY, token.value);
    localStorage.setItem(USERNAME_KEY, username.value);
    return result;
  }

  function logout() {
    token.value = "";
    username.value = "";
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USERNAME_KEY);
  }

  function authHeaders() {
    return token.value ? { Authorization: `Bearer ${token.value}` } : {};
  }

  return {
    token,
    username,
    isAuthenticated,
    login,
    logout,
    authHeaders
  };
});
