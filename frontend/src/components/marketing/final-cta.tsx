"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth-context";

/**
 * Enormous closing CTA (Tsenta-style) — a huge tight headline and a single
 * near-black pill button. Deliberately understated: no gradient, no card.
 */
export function FinalCta() {
  const { user } = useAuth();
  const primaryHref = user ? "/dashboard" : "/signin";

  return (
    <section className="mx-auto max-w-6xl px-6 py-24 md:py-32">
      <motion.p
        initial={{ opacity: 0, y: 8 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={{ duration: 0.5 }}
        className="text-sm text-muted-foreground"
      >
        Free to start. No card required.
      </motion.p>
      <motion.h2
        initial={{ opacity: 0, y: 14 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={{ duration: 0.6, delay: 0.05 }}
        className="mt-5 max-w-3xl font-display-tight text-5xl text-foreground md:text-6xl lg:text-7xl"
      >
        Stop sending the same resume everywhere.
      </motion.h2>
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={{ duration: 0.6, delay: 0.12 }}
        className="mt-8"
      >
        <Button asChild size="lg">
          <Link href={primaryHref}>{user ? "Open the dashboard" : "Get started"}</Link>
        </Button>
      </motion.div>
    </section>
  );
}
