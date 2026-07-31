import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import Home from "./site/Home";
import Privacy from "./site/Privacy";
import SiteLayout from "./layouts/SiteLayout";
import PlayLayout from "./layouts/PlayLayout";
import Landing from "./table/Landing";
import AccountArea from "./account/AccountArea";
import Room from "./table/Room";
import Host from "./tournament/Host";
import Organize from "./tournament/Organize";
import Play from "./tournament/Play";
import Admin from "./admin/Admin";
import "./index.css";
import "./table/table.css";
import "./account/account.css";
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
        {/* The account area serves the table and the tournament surfaces
            alike, so it is its own destination rather than a page inside
            either one. */}
        <Route path="/account" element={<PlayLayout><AccountArea section="overview" /></PlayLayout>} />
        <Route path="/account/games" element={<PlayLayout><AccountArea section="games" /></PlayLayout>} />
        <Route path="/account/notes" element={<PlayLayout><AccountArea section="notes" /></PlayLayout>} />
        <Route path="/account/settings" element={<PlayLayout><AccountArea section="settings" /></PlayLayout>} />
        {/* the dashboard lived here before it grew sections; links are out
            in the world (and in the privacy page's history) */}
        <Route path="/table/me" element={<Navigate to="/account" replace />} />
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
