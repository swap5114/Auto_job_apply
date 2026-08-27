"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  onAuthStateChanged,
  signInWithPopup,
  signOut as firebaseSignOut,
  type User,
} from "firebase/auth";
import { getFirebaseAuth, googleProvider } from "@/lib/firebase";
import { setAuthTokenGetter } from "@/lib/api";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  signInWithGoogle: () => Promise<User>;
  signOut: () => Promise<void>;
  getIdToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Wraps Firebase's onAuthStateChanged and exposes {user, signInWithGoogle,
 * signOut, getIdToken} -- mirrors pipeline-context.tsx's
 * "one shared subscription, many consumers" shape.
 *
 * On mount, registers a token getter with the API client (api.ts) so every
 * request made anywhere in the app automatically carries a fresh
 * Authorization header once a user is signed in -- see api.ts's
 * setAuthTokenGetter for the other half of this wiring.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const userRef = useRef<User | null>(null);

  const getIdToken = useCallback(async () => {
    if (!userRef.current) return null;
    try {
      return await userRef.current.getIdToken();
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    setAuthTokenGetter(getIdToken);

    const unsubscribe = onAuthStateChanged(getFirebaseAuth(), (u) => {
      userRef.current = u;
      setUser(u);
      setLoading(false);
    });

    return () => {
      unsubscribe();
      setAuthTokenGetter(null);
    };
  }, [getIdToken]);

  const signInWithGoogle = useCallback(async () => {
    const result = await signInWithPopup(getFirebaseAuth(), googleProvider);
    return result.user;
  }, []);

  const signOut = useCallback(async () => {
    await firebaseSignOut(getFirebaseAuth());
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, signInWithGoogle, signOut, getIdToken }}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Read the shared auth state. Safe to call from many components -- they
 * all share the single onAuthStateChanged subscription above.
 */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    // Fallback so components don't crash if used outside the provider.
    return {
      user: null as User | null,
      loading: false,
      signInWithGoogle: async () => {
        throw new Error("useAuth() called outside of an AuthProvider");
      },
      signOut: async () => {},
      getIdToken: async () => null,
    };
  }
  return ctx;
}
