import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { Components } from "react-markdown"
import { CodeBlock, langFromPath } from "./CodeBlock"

// Swiss markdown renderer: Prism code blocks, hairline rules, mono code,
// tight spacing. Styled per element (no Tailwind prose plugin) to keep the
// Swiss aesthetic discipline — audit-grade readability over editorial polish.

const COMPONENTS: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
  h1: ({ children }) => <h3 className="mt-3 mb-2 font-mono text-sm font-semibold uppercase tracking-wider text-ink">§ {children}</h3>,
  h2: ({ children }) => <h3 className="mt-3 mb-2 font-mono text-sm font-semibold uppercase tracking-wider text-ink">§ {children}</h3>,
  h3: ({ children }) => <h4 className="mt-3 mb-1 font-mono text-caption font-semibold uppercase tracking-wider text-ink-muted">{children}</h4>,
  h4: ({ children }) => <h4 className="mt-2 mb-1 font-mono text-caption font-semibold uppercase tracking-wider text-ink-muted">{children}</h4>,
  h5: ({ children }) => <h4 className="mt-2 mb-1 font-mono text-micro font-semibold uppercase tracking-wider text-ink-muted">{children}</h4>,
  h6: ({ children }) => <h4 className="mt-2 mb-1 font-mono text-micro font-semibold uppercase tracking-wider text-ink-faint">{children}</h4>,
  strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
  em: ({ children }) => <em className="italic text-ink">{children}</em>,
  ul: ({ children }) => <ul className="mb-2 ml-5 list-disc marker:text-ink-faint space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 ml-5 list-decimal marker:text-ink-faint space-y-1">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-rule pl-3 italic text-ink-muted">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-accent-500 underline-offset-2 hover:underline"
    >
      {children}
    </a>
  ),
  hr: () => <hr className="my-3 border-t border-dashed border-rule" />,
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="min-w-full border-collapse font-mono text-caption">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b border-rule">{children}</thead>,
  tbody: ({ children }) => <tbody className="divide-y divide-dashed divide-rule">{children}</tbody>,
  th: ({ children }) => (
    <th className="px-2 py-1 text-left font-mono text-micro uppercase tracking-wider text-ink-faint">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="px-2 py-1 text-ink">{children}</td>,
  // react-markdown v9 dropped the `inline` prop — detect via `className`:
  // fenced ``` blocks come with `language-xxx`, single-backticks come with no
  // class. That's the only reliable signal. AST `node.position` / `node.tagName`
  // would work too but className is simpler.
  code: ({ className, children, ...rest }: {
    className?: string
    children?: React.ReactNode
  } & React.HTMLAttributes<HTMLElement>) => {
    const isBlock = /language-[\w-]+/.test(className ?? "")
    if (!isBlock) {
      return (
        <code
          className="rounded-sm bg-sunken px-1 py-0.5 font-mono text-caption text-ink"
          {...rest}
        >
          {children}
        </code>
      )
    }
    const src = String(children ?? "").replace(/\n$/, "")
    const m = /language-([\w-]+)/.exec(className ?? "")
    const lang = m ? m[1] : langFromPath("")
    return (
      <div className="my-2">
        <CodeBlock lang={lang}>{src}</CodeBlock>
      </div>
    )
  },
  pre: ({ children }) => <>{children}</>, // CodeBlock already wraps in <pre>
}

export function Markdown({ children }: { children: string }) {
  return (
    <div className="font-sans text-sm text-ink break-words">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
