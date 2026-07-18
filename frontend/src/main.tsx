import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import App from "./App";
import Landing from "./table/Landing";
import Room from "./table/Room";
import "./index.css";
import "./table/table.css";

function LegacyRoomRedirect() {
  const { code = "" } = useParams();
  return <Navigate to={`/table/r/${code}`} replace />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/table" element={<Landing />} />
        <Route path="/table/r/:code" element={<Room />} />
        <Route path="/treachery" element={<Navigate to="/table" replace />} />
        <Route path="/treachery/r/:code" element={<LegacyRoomRedirect />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
