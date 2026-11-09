import { createRouter, createWebHistory } from "vue-router";

import DashboardView from "../views/DashboardView.vue";
import HistoryView from "../views/HistoryView.vue";
import LoginView from "../views/LoginView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "dashboard",
      component: DashboardView,
      meta: { requiresAuth: true }
    },
    {
      path: "/history",
      name: "history",
      component: HistoryView,
      meta: { requiresAuth: true }
    },
    {
      path: "/login",
      name: "login",
      component: LoginView
    }
  ]
});

router.beforeEach((to) => {
  const hasToken = Boolean(localStorage.getItem("iiot_admin_token"));
  if (to.meta.requiresAuth && !hasToken) {
    return { name: "login" };
  }
  if (to.name === "login" && hasToken) {
    return { name: "dashboard" };
  }
  return true;
});

export default router;
