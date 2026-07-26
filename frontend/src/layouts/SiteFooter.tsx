import { Link } from "react-router-dom";
import FanContentNotice from "../FanContentNotice";

/** The whole footer: the required disclosure and the privacy page. Nothing
 *  else on purpose — more footer is designing for a future we haven't picked. */
export default function SiteFooter() {
  return (
    <footer className="site-footer">
      <p className="site-footer-links">
        <Link to="/privacy">Privacy</Link>
      </p>
      <FanContentNotice />
    </footer>
  );
}
