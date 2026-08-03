import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import Home from "./site/Home";
import Privacy from "./site/Privacy";
import SiteLayout from "./layouts/SiteLayout";
import PlayLayout from "./layouts/PlayLayout";
import Landing from "./table/Landing";
import AccountArea from "./account/AccountArea";
import LinkLanding from "./account/LinkLanding";
import Rulings from "./cards/Rulings";
import Room from "./table/Room";
import Host from "./tournament/Host";
import Organize from "./tournament/Organize";
import Play from "./tournament/Play";
import Admin from "./admin/Admin";
import "./index.css";
import "./table/table.css";
import "./account/account.css";
import "./cards/rulings.css";
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
        {/* A play aid rather than a part of any one game: no account, no room,
            no tournament. Its own module so it reaches into neither the table
            surface nor the games registry — rulings are a
            Wizards-and-Scryfall shaped problem and there is only one game
            using them so far. */}
        <Route path="/rulings" element={<PlayLayout><Rulings /></PlayLayout>} />
        <Route path="/table/r/:code" element={<Room />} />
        {/* The account area serves the table and the tournament surfaces
            alike, so it is its own destination rather than a page inside
            either one. */}
        <Route path="/account" element={<PlayLayout><AccountArea section="overview" /></PlayLayout>} />
        <Route path="/account/games" element={<PlayLayout><AccountArea section="games" /></PlayLayout>} />
        <Route path="/account/notes" element={<PlayLayout><AccountArea section="notes" /></PlayLayout>} />
        <Route path="/account/settings" element={<PlayLayout><AccountArea section="settings" /></PlayLayout>} />
        {/* Where the links in our two emails land. No sign-in gate: a
            confirmation link is opened from an inbox, routinely on a different
            device from the one that asked, and a reset link exists precisely
            because nobody can sign in. The token in the fragment is the
            authorization. */}
        <Route path="/account/verify" element={<PlayLayout><LinkLanding purpose="verify" /></PlayLayout>} />
        <Route path="/account/reset" element={<PlayLayout><LinkLanding purpose="reset" /></PlayLayout>} />
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
