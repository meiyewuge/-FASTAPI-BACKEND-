/**
 * 登录页 —— 系统唯一入口（skeleton）。
 * 只做 3 件事：手机号/token 登录、自动绑定 tenant_id、进入系统。
 */
import { useState } from "react";
import { login } from "../api/client";

export default function Login() {
  const [phone, setPhone] = useState("");
  return (
    <div className="login">
      <h1>美业AI视频系统 V4.0</h1>
      <input placeholder="手机号 / token" value={phone} onChange={(e) => setPhone(e.target.value)} />
      <button onClick={() => login(phone)}>进入系统</button>
    </div>
  );
}
