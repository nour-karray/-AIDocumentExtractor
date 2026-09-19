"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { fetchCurrentUser, fetchMeta } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    fetchMeta()
      .then((meta) => {
        if (!meta.auth?.enabled) {
          router.replace("/dashboard");
          return;
        }
        fetchCurrentUser()
          .then(() => router.replace("/dashboard"))
          .catch(() => router.replace("/login"));
      })
      .catch(() => router.replace("/login"));
  }, [router]);
  return <main className="grid min-h-screen place-items-center">Chargement de DocIA...</main>;
}
