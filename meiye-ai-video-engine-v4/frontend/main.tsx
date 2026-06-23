// 前端入口（skeleton）。极简 SaaS：仅 Login 与 Workbench 两页。
import React from "react";
import ReactDOM from "react-dom/client";
import Workbench from "./pages/Workbench";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Workbench />
  </React.StrictMode>
);
