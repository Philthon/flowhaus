import { createContext, useContext } from "react";

import type { Terms } from "./api";

/** What one "row" is called in the current flow: contact, lead, invoice, account… */
export const TermsContext = createContext<Terms>({ item: "item", items: "items" });
export const useTerms = () => useContext(TermsContext);
