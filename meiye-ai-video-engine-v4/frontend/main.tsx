/**
 * 前端入口 — Login + Workbench + AdminPanel 三页路由 + 401 自动跳登录。
 * /admin 路由守卫在 AdminPanel 内部（JWT role 检查，非 admin 跳工作台）。
 */
import React from "react";
import ReactDOM from "react-dom/client";
import {
  createHashRouter,
  RouterProvider,
  Navigate,
  useNavigate,
} from "react-router-dom";
import { getToken, register401 } from "./api/client";
import Login from "./pages/Login";
import Workbench from "./pages/Workbench";
import AdminPanel from "./pages/AdminPanel";
import "./styles.css";

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** 注册 401 回调，任何 API 返回 401 时自动跳登录 */
function App() {
  const navigate = useNavigate();
  React.useEffect(() => {
    register401(() => navigate("/login", { replace: true }));
  }, [navigate]);
  return null;
}

const router = createHashRouter([
  { path: "/login", element: <Login /> },
  {
    path: "/workbench",
    element: (
      <>
        <RequireAuth><Workbench /></RequireAuth>
        <App />
      </>
    ),
  },
  {
    path: "/admin",
    element: (
      <>
        <RequireAuth><AdminPanel /></RequireAuth>
        <App />
      </>
    ),
  },
  { path: "*", element: <Navigate to="/workbench" replace /> },
]);

// App 组件也需要在 router 外部注册 401，确保 login 页也能处理
router.subscribe(() => {});  // 触发初始加载

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
