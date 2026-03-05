import { Instrument_Sans } from "next/font/google";

const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer
      className={`${instrumentSans.className} relative h-full w-full overflow-hidden bg-background text-foreground`}
    >
      <div className="mx-auto flex h-full w-full max-w-6xl pr-0 pt-4 pb-4 pl-0 sm:pr-0 sm:pt-8 sm:pb-8 sm:pl-0">
        {/* Green rounded box on the left, fading to the right */}
        <div className="relative w-[calc(100%+2rem)] -ml-8 sm:w-[calc(100%+4rem)] sm:-ml-16">
          {/* Leaked gradient glow (outside the box) */}
          <div className="pointer-events-none absolute -inset-x-28 -inset-y-24 -z-10 bg-[linear-gradient(90deg,_rgba(208,240,192,0.65),_rgba(208,240,192,0.18),_rgba(208,240,192,0))] blur-3xl dark:bg-[linear-gradient(90deg,_rgba(208,240,192,0.12),_rgba(208,240,192,0.04),_rgba(208,240,192,0))]" />

          {/* Gradient-as-border (fades on right side) */}
          <div className="rounded-[28px] bg-[linear-gradient(90deg,_rgba(208,240,192,0.72),_rgba(208,240,192,0.24),_rgba(208,240,192,0))] p-[1px] shadow-[0_34px_140px_rgba(208,240,192,0.10)] dark:bg-[linear-gradient(90deg,_rgba(208,240,192,0.12),_rgba(208,240,192,0.04),_rgba(208,240,192,0))] dark:shadow-[0_34px_140px_rgba(208,240,192,0.08)] [mask-image:linear-gradient(to_right,_#000_0%,_#000_80%,_transparent_100%)] [-webkit-mask-image:linear-gradient(to_right,_#000_0%,_#000_80%,_transparent_100%)]">
            <div className="relative overflow-visible rounded-[27px] bg-[linear-gradient(90deg,_rgba(208,240,192,0.45),_rgba(208,240,192,0.12),_rgba(208,240,192,0))] px-8 pt-8 pb-16 dark:bg-[linear-gradient(90deg,_rgba(208,240,192,0.08),_rgba(208,240,192,0.03),_rgba(208,240,192,0))] sm:px-12 sm:pt-12 sm:pb-20">
              <div className="pointer-events-none absolute inset-0">
                <div className="absolute left-[-18%] top-[-25%] h-[150%] w-[55%] rounded-full bg-[radial-gradient(circle_at_center,_rgba(208,240,192,0.68),_transparent_65%)] blur-3xl dark:bg-[radial-gradient(circle_at_center,_rgba(208,240,192,0.12),_transparent_65%)]" />
              </div>

              <div className="relative flex h-full min-h-[70vh] flex-col sm:min-h-[75vh]">
                <div className="text-sm font-semibold text-black transition duration-200 ease-out hover:text-black hover:scale-[1.16] origin-left">
                  Weave Studio
                </div>

                <div className="mt-16 sm:mt-20 pr-8 sm:pr-16">
                  <h2 className="text-[clamp(4.1rem,7.9vw,7.6rem)] font-semibold leading-[0.95] tracking-tight text-black transition duration-200 ease-out hover:text-black hover:scale-[1.14] origin-left">
                    Let’s work together.
                  </h2>
                  <p className="mt-5 max-w-xl text-sm font-medium text-black/75 sm:text-base transition duration-200 ease-out hover:text-black/75 hover:scale-[1.12] origin-left">
                    If this all sounds like what your brand needs.
                  </p>

                  <div className="mt-8">
                    <a
                      href="https://cal.com/"
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 rounded-full bg-background/72 px-4 py-2.5 text-xs font-semibold text-black backdrop-blur transition duration-200 ease-out hover:bg-background/92 hover:text-black hover:scale-[1.14] origin-left shadow-[0_10px_28px_rgba(0,0,0,0.08)] hover:shadow-[0_22px_64px_rgba(0,0,0,0.14)] dark:shadow-[0_10px_28px_rgba(0,0,0,0.34)] dark:hover:shadow-[0_22px_64px_rgba(0,0,0,0.46)]"
                    >
                      <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-foreground/10 text-[10px]">
                        ↗
                      </span>
                      <span className="text-black/75 hover:text-black/75">
                        [Replace with your cal.com link]
                      </span>
                      <span>cal.com</span>
                    </a>
                  </div>
                </div>

                <div className="mt-auto pt-12">
                  <div className="grid gap-10 sm:grid-cols-2 sm:gap-12">
                    <div className="group transition duration-200 ease-out hover:scale-[1.12] origin-left">
                      <div className="h-px w-full bg-gradient-to-r from-foreground/28 via-foreground/14 to-transparent transition group-hover:from-black/65 group-hover:via-black/24" />
                      <div className="mt-3 text-[11px] font-medium text-black/75 transition group-hover:text-black/75">
                        weave.design
                      </div>
                    </div>
                    <div className="group transition duration-200 ease-out hover:scale-[1.12] origin-left">
                      <div className="h-px w-full bg-gradient-to-r from-foreground/28 via-foreground/14 to-transparent transition group-hover:from-black/65 group-hover:via-black/24" />
                      <div className="mt-3 text-[11px] font-medium text-black/75 transition group-hover:text-black/75">
                        © {year} Weavelabs. All rights reserved.
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}

