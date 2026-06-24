/**
 * 前端入口 — Login + Workbench 两页路由。
 */
import React from "react";
import ReactDOM from "react-dom/client";
import {
  createHashRouter,
  RouterProvider,
  Navigate,
} from "react-router-dom";
import { getToken } from "./api/client";
import Login from "./pages/Login";
import Workbench from "./pages/Workbench";
import "./styles.css";

// 路由守卫：未登录跳 Login，已登录跳 Workbench
function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

const router = createHashRouter([
  {
    path: "/login",
    element: <Login />,
  },
  {
    path: "/workbench",
    element: (
      <RequireAuth>
        <Workbench />
      </RequireAuth>
    ),
  },
  {
    path: "*",
    element: <Navigate to="/workbench" replace />,
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
// 前端入口（skeleton）。极简 SaaS：仅 Login 与 Workbench 两页。
import React from "react";
import ReactDOM from "react-dom/client";
import Workbench from "./pages/Workbench";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Workbench />
  </React.StrictMode>
);
