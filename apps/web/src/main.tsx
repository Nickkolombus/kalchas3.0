import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AdminApp } from "./Admin";
import { App } from "./App";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/admin.css";

const admin = window.location.pathname.replace(/\/+$/, "") === "/admin";

createRoot(document.getElementById("root")!).render(
  <StrictMode>{admin ? <AdminApp /> : <App />}</StrictMode>,
);
