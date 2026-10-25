import { createRoot } from 'react-dom/client';
import SessionShell from './SessionShell';
import '@fontsource/ibm-plex-sans-thai/400.css';
import '@fontsource/ibm-plex-sans-thai/500.css';
import '@fontsource/ibm-plex-sans-thai/600.css';
import '@fontsource/ibm-plex-sans-thai/700.css';
import '@fontsource-variable/manrope';
import '@fontsource/kanit/thai-700.css';
import '@fontsource/kanit/thai-800.css';
import './styles.css';
import './theme.css';
import './mint.css';
import './polish.css';

createRoot(document.getElementById('root')!).render(<SessionShell />);
