import { useState } from "react"
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter"
import oneDark from "react-syntax-highlighter/dist/esm/styles/prism/one-dark"
import { redactTokens } from "./redact"

// Full Prism bundle: ~200kB for complete language coverage. Swiss-aligned:
// zero surprises for audit-grade receipts, any file type in a session renders
// correctly. Loaded only when SessionDetailPage is visited (code-split point).
//
// Prism ships ~300 languages out of the box — the type below is `string`
// because listing them all adds noise without value.

export type CodeLang = string

// Map file-extension → Prism language alias. Defaults to the file extension
// itself when unmapped, which works for most languages Prism supports natively
// (py, rs, go, java, kt, swift, rb, php, etc). Only add entries here when the
// extension doesn't match Prism's canonical alias.
const _EXT_TO_LANG: Record<string, string> = {
  py: "python", pyi: "python",
  rb: "ruby",
  rs: "rust",
  kt: "kotlin", kts: "kotlin",
  ts: "typescript", mts: "typescript", cts: "typescript",
  tsx: "tsx",
  js: "javascript", mjs: "javascript", cjs: "javascript",
  jsx: "jsx",
  md: "markdown", mdx: "markdown",
  yml: "yaml", yaml: "yaml",
  sql: "sql",
  css: "css", scss: "scss", sass: "sass", less: "less",
  json: "json", jsonc: "json",
  sh: "bash", bash: "bash", zsh: "bash", fish: "bash",
  html: "markup", htm: "markup", xml: "markup", svg: "markup", vue: "markup",
  toml: "toml",
  ini: "ini", conf: "ini",
  go: "go",
  java: "java",
  c: "c", h: "c",
  cpp: "cpp", cc: "cpp", hpp: "cpp", hxx: "cpp",
  cs: "csharp",
  swift: "swift",
  php: "php",
  dockerfile: "docker",
  tf: "hcl", hcl: "hcl",
  graphql: "graphql", gql: "graphql",
  proto: "protobuf",
  lua: "lua",
  r: "r",
  dart: "dart",
  scala: "scala",
  clj: "clojure", cljs: "clojure",
  elm: "elm",
  erl: "erlang",
  ex: "elixir", exs: "elixir",
  hs: "haskell",
  ml: "ocaml",
  nim: "nim",
  pl: "perl", pm: "perl",
  vim: "vim",
  zig: "zig",
  env: "bash",
  make: "makefile", mk: "makefile",
}

export function langFromPath(path: string | undefined | null): string {
  if (!path) return "text"
  // Special-case Dockerfile / Makefile (no extension).
  const basename = path.split("/").pop() ?? path
  if (/^Dockerfile/i.test(basename)) return "docker"
  if (/^Makefile$/i.test(basename)) return "makefile"
  const m = /\.([A-Za-z0-9]+)$/.exec(basename)
  if (!m) return "text"
  const ext = m[1].toLowerCase()
  return _EXT_TO_LANG[ext] ?? ext // fallback: use extension as-is
}

interface CodeBlockProps {
  children: string
  lang?: CodeLang
  /** Extra classes merged onto the outer <pre> (e.g. a colored left border). */
  className?: string
}

// Override one-dark's chrome to align with the Swiss dark-paper palette.
// Keeps token colors (Prism's strings/keywords/numbers) but swaps the
// background to bg-sunken so the block sits inside the surface rhythm.
const PRE_STYLE: React.CSSProperties = {
  margin: 0,
  padding: "0.75rem",
  background: "transparent", // parent <pre> paints bg-sunken via className
  fontFamily: "inherit",
  fontSize: "inherit",
  lineHeight: "inherit",
  maxHeight: "20rem",
  overflow: "auto",
}

const CODE_STYLE: React.CSSProperties = {
  fontFamily: "inherit",
  background: "transparent",
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {
      /* navigator.clipboard unavailable — silent */
    }
  }
  return (
    <button
      type="button"
      onClick={onCopy}
      aria-label={copied ? "Copied to clipboard" : "Copy to clipboard"}
      title={copied ? "Copied!" : "Copy"}
      className={
        "absolute right-1.5 top-1.5 z-10 rounded-sm border border-rule bg-sunken/80 " +
        "px-1.5 py-0.5 font-mono text-micro uppercase tracking-wider " +
        "text-ink-faint hover:text-ink hover:bg-sunken " +
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
        "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
      }
    >
      {copied ? "copied" : "copy"}
    </button>
  )
}

export function CodeBlock({ children, lang = "text", className = "" }: CodeBlockProps) {
  const safe = redactTokens(children)
  if (lang === "text") {
    return (
      <div className="relative">
        <pre
          className={
            "max-h-80 overflow-auto rounded-sm bg-sunken p-3 pr-14 " +
            "font-mono text-sm leading-relaxed text-ink whitespace-pre-wrap break-all " +
            className
          }
        >
          {safe}
        </pre>
        <CopyButton value={safe} />
      </div>
    )
  }
  return (
    <div
      className={
        "relative rounded-sm bg-sunken font-mono text-sm leading-relaxed " + className
      }
    >
      <SyntaxHighlighter
        language={lang}
        style={oneDark}
        PreTag="pre"
        customStyle={PRE_STYLE}
        codeTagProps={{ style: CODE_STYLE }}
        wrapLongLines
      >
        {safe}
      </SyntaxHighlighter>
      <CopyButton value={safe} />
    </div>
  )
}
