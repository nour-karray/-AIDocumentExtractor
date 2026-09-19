import { redirect } from "next/navigation";

type ResultsPageProps = {
  searchParams?: Promise<{ entry?: string | string[] }>;
};

export default async function ResultsPage({ searchParams }: ResultsPageProps) {
  const params = searchParams ? await searchParams : undefined;
  const entryValue = params?.entry;
  const entryKey = Array.isArray(entryValue) ? entryValue[0] : entryValue;
  redirect(entryKey ? `/documents?entry=${entryKey}` : "/documents");
}
