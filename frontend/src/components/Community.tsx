"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/AuthProvider";
import { getCity, timeAgo } from "@/lib/identity";
import { PostCard } from "@/lib/types";

export function Community({
  slug,
  posts,
  onChange,
}: {
  slug: string;
  posts: PostCard[];
  onChange: () => void;
}) {
  const { user, ready } = useAuth();
  const pathname = usePathname();
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const next = `/login?next=${encodeURIComponent(pathname || `/product/${slug}`)}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    setBusy(true);
    try {
      await api.post({
        product_slug: slug,
        body,
        location_label: getCity(),
        counts_as_report: true,
      });
      setBody("");
      onChange();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="grid gap-4">
      {ready && user ? (
        <form onSubmit={submit} className="card p-5">
          <div className="serif text-xl">Add your story</div>
          <p className="mt-1 text-sm text-[#5a6d80]">
            Posting as <strong className="text-[#1a365d]">{user.displayName}</strong>. Posts are
            public. If you describe what happened, it also helps the overall picture for this product.
          </p>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={3}
            placeholder="What happened with this product?"
            className="field mt-4 w-full"
          />
          <button
            disabled={busy || body.trim().length < 4}
            className="btn-primary mt-3 px-4 py-2 text-sm disabled:opacity-40"
          >
            {busy ? "Sharing…" : "Share with neighbors"}
          </button>
        </form>
      ) : (
        <div className="card p-5">
          <div className="serif text-xl">Add your story</div>
          <p className="mt-1 text-sm text-[#5a6d80]">
            Sign in to share what happened. Browsing stays open to everyone.
          </p>
          <Link href={next} className="btn-primary mt-4 inline-block px-4 py-2 text-sm">
            Log in to share
          </Link>
        </div>
      )}
      {posts.map((post) => (
        <PostItem key={post.id} post={post} onChange={onChange} loginHref={next} />
      ))}
    </section>
  );
}

function PostItem({
  post,
  onChange,
  loginHref,
}: {
  post: PostCard;
  onChange: () => void;
  loginHref: string;
}) {
  const { user } = useAuth();
  const [comment, setComment] = useState("");
  const liked = Boolean(user && post.liked_by_subs?.includes(user.sub));

  return (
    <article className="card p-5">
      <div className="flex items-center justify-between gap-3 text-sm text-[#5a6d80]">
        <strong className="text-[#1a365d]">{post.display_name}</strong>
        <span>{timeAgo(post.created_at)}</span>
      </div>
      {post.location_label && <div className="mt-1 text-xs text-[#5b8fb5]">📍 {post.location_label}</div>}
      <p className="mt-3 leading-relaxed">{post.body}</p>
      <div className="mt-4 flex gap-3">
        {user ? (
          <button
            onClick={async () => {
              await api.like(post.id);
              onChange();
            }}
            className={`rounded-full px-3 py-1 text-sm ${liked ? "bg-[#f6e7ea] text-[#c45c6a]" : "bg-[#f6f1e8]"}`}
          >
            ♥ {post.like_count}
          </button>
        ) : (
          <Link href={loginHref} className="rounded-full bg-[#f6f1e8] px-3 py-1 text-sm">
            ♥ {post.like_count}
          </Link>
        )}
      </div>
      <div className="mt-4 space-y-2 border-t border-[#e4d9c8] pt-3">
        {post.comments.map((item) => (
          <div key={item.id} className="text-sm">
            <span className="text-[#5b8fb5]">{item.display_name}</span>
            <span className="text-[#5a6d80]"> · {item.body}</span>
          </div>
        ))}
        {user ? (
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              if (!comment.trim()) return;
              await api.comment(post.id, { body: comment });
              setComment("");
              onChange();
            }}
            className="flex gap-2"
          >
            <input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Write a kind reply"
              className="field flex-1 rounded-full"
            />
          </form>
        ) : (
          <Link href={loginHref} className="text-sm text-[#5b8fb5]">
            Sign in to reply
          </Link>
        )}
      </div>
    </article>
  );
}
