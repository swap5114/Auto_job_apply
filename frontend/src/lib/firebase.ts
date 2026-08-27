/**
 * Firebase client-side initialization (Phase 3.5).
 *
 * The config below is the *public* Firebase web config (apiKey, authDomain,
 * etc.) -- safe to ship to the browser, unlike the backend's service
 * account key (config/.env's FIREBASE_SERVICE_ACCOUNT_PATH, never
 * exposed here). Values come from NEXT_PUBLIC_* env vars so they can
 * differ between local dev and a deployed frontend without a code change
 * -- see frontend/.env.local.example for the full list.
 *
 * getFirebaseApp() lazily initializes exactly one app instance and reuses
 * it on every call (Next.js can re-evaluate modules across fast-refresh in
 * dev, so a bare top-level initializeApp() call would throw
 * "Firebase App named '[DEFAULT]' already exists" the second time).
 */

import { getApps, getApp, initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, type Auth } from "firebase/auth";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

let app: FirebaseApp | null = null;
let auth: Auth | null = null;

export function getFirebaseApp(): FirebaseApp {
  if (!app) {
    app = getApps().length ? getApp() : initializeApp(firebaseConfig);
  }
  return app;
}

export function getFirebaseAuth(): Auth {
  if (!auth) {
    auth = getAuth(getFirebaseApp());
  }
  return auth;
}

export const googleProvider = new GoogleAuthProvider();
