import React from "react";
import ReactDOM from "react-dom/client";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./styles/components.css";
import "./features/analysis/analysis.css";
import "./features/allocation/allocation.css";
import "./features/approval/approval.css";
import "./styles/dashboard.css";
import "./styles/editorial.css";
import "./styles/landing.css";
import "./styles/login.css";
import "./styles/responsive.css";
import "./styles/datefield.css";
import "./styles/apple.css";
import { App } from "./app/App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
