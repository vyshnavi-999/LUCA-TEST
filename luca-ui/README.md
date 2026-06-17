# UI for Luca (Progressive Web App)

This project is a production-ready, mobile-first Progressive Web Application (PWA) built from scratch using Vite, React, and Vanilla CSS. It is structured to be scalable and maintainable, ensuring a smooth transition to AWS Amplify and potential future packaging for the Google Play Store (via Trusted Web Activity).

---

## 📂 Project Architecture & File Rationale

To ensure the codebase never feels "clumsy" or confusing, strict separation of concerns has been implemented. Below is the documentation of every critical file in the project and **why** it was created:

### Configuration Files
- **`vite.config.js`**: Replaced standard Vite config. *Why?* We added `vite-plugin-pwa` here to automatically generate the Service Worker and `manifest.webmanifest`. This file tells the compiler how to cache static assets for offline use.
- **`index.html`**: The main entry point. *Why modified?* It was updated to include PWA `<meta>` tags (like `theme-color` and `apple-touch-icon`) ensuring the app behaves like a native application on both iOS and Android.

### Styles
- **`src/index.css`**: The single source of truth for global styling. *Why?* Instead of importing massive CSS libraries, we created a lightweight design system using CSS Variables (`--bg-color`, `--primary-color`). It controls the dark aesthetic and the bottom radial gradient to exactly match the target design, while keeping performance optimal.

### Components (`src/components/`)
*We isolate reusable UI pieces here so `App.jsx` doesn't become bloated.*
- **`PWABadge.jsx` & `PWABadge.css`**: A notification toast component. *Why?* PWAs cache aggressively. If you release an update, users might not see it unless they reload. This component detects background updates and prompts the user to refresh to apply the new version.
- **`InstallPrompt.jsx`**: An interactive UI element. *Why?* It detects if the user is in a browser (like Chrome/Safari) and provides a clean button to natively install the app to their home screen.

### Custom Hooks (`src/hooks/`)
*We separate logic from UI components to make code readable and reusable.*
- **`useInstallPrompt.js`**: React Hook. *Why?* Browsers fire a `beforeinstallprompt` event when an app is ready to be installed. This hook intercepts that event, prevents the default ugly browser prompt, and passes the event to our clean `InstallPrompt.jsx` component instead.

### The Main Application
- **`src/App.jsx`**: The root layout view. *Why?* This assembles the components (Header, Glowing Star, Welcome text, Bottom Navigation) into the unified UI. It remains clean because complex PWA logic was abstracted away into the components and hooks mentioned above.

---

## 🚀 Deployment & Maintenance

### Live Application
**Production URL**: [https://main.d21xc8qnkn17pl.amplifyapp.com/](https://main.d21xc8qnkn17pl.amplifyapp.com/)

### AWS Amplify
This project is fully ready for AWS Amplify deployment via GitHub. 
Because `vite.config.js` is already handling PWA generation, simply point Amplify to this repository. The default build settings (`npm run build` with the `dist` directory) will correctly serve the application over HTTPS, which instantly enables native PWA installation across mobile devices.

### Local Development
- Start development server: `npm run dev`
- Build for production: `npm run build`
- Test the production build (Required for testing Service Workers): `npm run preview`