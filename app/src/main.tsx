import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
// import LicenseGate from "./components/LicenseGate"; // disabled — enable when ready to ship

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {/* LicenseGate disabled — re-wrap <App /> when ready to enable login/encryption */}
    <App />
  </React.StrictMode>,
);
