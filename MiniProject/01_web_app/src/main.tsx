import { createRoot } from 'react-dom/client';
import App from './App';
import '@fontsource/ibm-plex-sans-thai/400.css';
import '@fontsource/ibm-plex-sans-thai/500.css';
import '@fontsource/ibm-plex-sans-thai/600.css';
import '@fontsource/ibm-plex-sans-thai/700.css';
import '@fontsource-variable/manrope';
import './styles.css';

createRoot(document.getElementById('root')!).render(<App />);
