import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App";
import Landing from "./treachery/Landing";
import Room from "./treachery/Room";
import "./index.css";
import "./treachery/treachery.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/treachery" element={<Landing />} />
        <Route path="/treachery/r/:code" element={<Room />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
