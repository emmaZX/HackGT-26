"use client";

import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import { getCity, getDisplayName, timeAgo } from "@/lib/identity";
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
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.post({
        product_slug: slug,
        body,
        display_name: getDisplayName(),
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
      <form onSubmit={submit} className="card p-5">
        <div className="serif text-xl">Add your story</div>
        <p className="mt-1 text-sm text-[#5a6d80]">
          Posts are public. If you describe what happened, it also helps the overall picture for this product.
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
      {posts.map((post) => (
        <PostItem key={post.id} post={post} onChange={onChange} />
      ))}
    </section>
  );
}

function PostItem({ post, onChange }: { post: PostCard; onChange: () => void }) {
  const [comment, setComment] = useState("");
  const name = getDisplayName();
  const liked = post.liked_by.includes(name);

  return (
    <article className="card p-5">
      <div className="flex items-center justify-between gap-3 text-sm text-[#5a6d80]">
        <strong className="text-[#1a365d]">{post.display_name}</strong>
        <span>{timeAgo(post.created_at)}</span>
      </div>
      {post.location_label && <div className="mt-1 text-xs text-[#5b8fb5]">📍 {post.location_label}</div>}
      <p className="mt-3 leading-relaxed">{post.body}</p>
      <div className="mt-4 flex gap-3">
        <button
          onClick={async () => {
            await api.like(post.id, name);
            onChange();
          }}
          className={`rounded-full px-3 py-1 text-sm ${liked ? "bg-[#f6e7ea] text-[#c45c6a]" : "bg-[#f6f1e8]"}`}
        >
          ♥ {post.like_count}
        </button>
      </div>
      <div className="mt-4 space-y-2 border-t border-[#e4d9c8] pt-3">
        {post.comments.map((item) => (
          <div key={item.id} className="text-sm">
            <span className="text-[#5b8fb5]">{item.display_name}</span>
            <span className="text-[#5a6d80]"> · {item.body}</span>
          </div>
        ))}
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (!comment.trim()) return;
            await api.comment(post.id, { body: comment, display_name: name });
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
      </div>
    </article>
  );
}
