import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import Home from "./site/Home";
import Privacy from "./site/Privacy";
import SiteLayout from "./layouts/SiteLayout";
import PlayLayout from "./layouts/PlayLayout";
import Landing from "./table/Landing";
import Dashboard from "./table/Dashboard";
import Room from "./table/Room";
import Host from "./tournament/Host";
import Organize from "./tournament/Organize";
import Play from "./tournament/Play";
import Admin from "./admin/Admin";
import "./index.css";
import "./table/table.css";
import "./tournament/tournament.css";
import "./admin/admin.css";
import "./layouts/layouts.css";

function LegacyRoomRedirect() {
  const { code = "" } = useParams();
  return <Navigate to={`/table/r/${code}`} replace />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<SiteLayout><Home /></SiteLayout>} />
        <Route path="/privacy" element={<SiteLayout><Privacy /></SiteLayout>} />
        <Route path="/table" element={<PlayLayout><Landing /></PlayLayout>} />
        <Route path="/table/r/:code" element={<Room />} />
        <Route path="/table/me" element={<PlayLayout><Dashboard /></PlayLayout>} />
        <Route path="/tournament" element={<PlayLayout><Host /></PlayLayout>} />
        <Route path="/tournament/:code" element={<PlayLayout><Play /></PlayLayout>} />
        <Route path="/tournament/:code/organize" element={<Navigate to="pods" replace />} />
        <Route path="/tournament/:code/organize/:section" element={<Organize />} />
        {/* unlisted: nothing links here. The server enforces access, not the absence of a link. */}
        <Route path="/admin" element={<Navigate to="/admin/overview" replace />} />
        <Route path="/admin/:section" element={<Admin />} />
        <Route path="/treachery" element={<Navigate to="/table" replace />} />
        <Route path="/treachery/r/:code" element={<LegacyRoomRedirect />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
