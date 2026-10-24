// Development-only component harness. Not part of the production entry/build.
import { createRoot } from 'react-dom/client';
import App from '../src/App';
import '@fontsource/ibm-plex-sans-thai/400.css';
import '@fontsource/ibm-plex-sans-thai/600.css';
import '@fontsource-variable/manrope';
import '../src/styles.css';
import '../src/theme.css';
import '../src/mint.css';
import '../src/polish.css';
createRoot(document.getElementById('root')!).render(<App />);
