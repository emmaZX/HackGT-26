import Link from "next/link";

export function NotFoundPrompt({
  query,
  title = "We do not have that item yet",
}: {
  query?: string;
  title?: string;
}) {
  const href = query?.trim()
    ? `/report?product=${encodeURIComponent(query.trim())}`
    : "/report";

  return (
    <div className="card mt-8 p-6">
      <h2 className="serif text-3xl">{title}</h2>
      <p className="mt-2 text-[#627290]">
        Nothing in the catalog matches
        {query?.trim() ? (
          <>
            {" "}
            <strong className="text-[#031d4e]">“{query.trim()}”</strong>
          </>
        ) : (
          " that search"
        )}
        . If you used it and something went wrong, a neighbor note helps everyone else see it.
      </p>
      <Link href={href} className="btn-primary mt-5 inline-block px-5 py-3 text-sm">
        Submit a report
      </Link>
    </div>
  );
}
