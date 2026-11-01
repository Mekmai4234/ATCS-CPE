import { createContext } from 'react';
import type { Api } from './api';
export const TaskApiContext = createContext<Api | null>(null);
