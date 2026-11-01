// Development-only component harness. Not part of the production entry/build.
import { createRoot } from 'react-dom/client';
import App from '../src/App';
import '@fontsource/ibm-plex-sans-thai/400.css';
import '@fontsource/ibm-plex-sans-thai/600.css';
import '@fontsource-variable/manrope';
import '@fontsource/kanit/thai-700.css';
import '@fontsource/kanit/thai-800.css';
import '../src/styles.css';
import '../src/theme.css';
import '../src/mint.css';
import '../src/polish.css';
import '../src/v5.css';
import '../src/results-v5.css';
import '../src/secondary-v5.css';
import '../src/auth-v5.css';
import '../src/job-recovery.css';
createRoot(document.getElementById('root')!).render(<App />);
