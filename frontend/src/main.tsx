import React from "react";
import { createRoot } from "react-dom/client";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing root element");
}

createRoot(root).render(
  <React.StrictMode>
    <main>
      <h1>Черновик рекомендаций для закупок</h1>
      <p>Интерфейс разрабатывается участником UI.</p>
    </main>
  </React.StrictMode>,
);
