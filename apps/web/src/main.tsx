import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AdminApp } from "./Admin";
import { App } from "./App";
import { WatchlistApp, isWatchlistPath } from "./Watchlist";
import { PicksProvider } from "./WatchlistPicks";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/admin.css";
import "./styles/mobile.css";
import "./styles/watchlist.css";

const path = window.location.pathname;
const admin = path.replace(/\/+$/, "") === "/admin";
const page = admin ? (
  <AdminApp />
) : isWatchlistPath(path) ? (
  <WatchlistApp />
) : (
  <PicksProvider>
    <App />
  </PicksProvider>
);

createRoot(document.getElementById("root")!).render(<StrictMode>{page}</StrictMode>);
