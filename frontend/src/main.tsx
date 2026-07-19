import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import App from "./App";
import Landing from "./table/Landing";
import Dashboard from "./table/Dashboard";
import Room from "./table/Room";
import Host from "./tournament/Host";
import Organize from "./tournament/Organize";
import Play from "./tournament/Play";
import "./index.css";
import "./table/table.css";
import "./tournament/tournament.css";

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
        <Route path="/table/me" element={<Dashboard />} />
        <Route path="/tournament" element={<Host />} />
        <Route path="/tournament/:code" element={<Play />} />
        <Route path="/tournament/:code/organize" element={<Organize />} />
        <Route path="/treachery" element={<Navigate to="/table" replace />} />
        <Route path="/treachery/r/:code" element={<LegacyRoomRedirect />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
