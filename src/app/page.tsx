import { Instrument_Sans } from "next/font/google";
import { Footer } from "@/components/footer";
import { FullpageScroll } from "@/components/fullpage-scroll";
import { ThemedLogo } from "@/components/themed-logo";
import Image from "next/image";

const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export default function Home() {
  return (
    <FullpageScroll sectionCount={11}>
      {/* Section 1: Home */}
      <section className="relative h-screen w-full snap-start overflow-hidden bg-background text-foreground">
        {/* Soft gradient haze */}
        <div className="pointer-events-none absolute inset-x-0 bottom-[-22vh] h-[52vh]">
          <div className="absolute left-1/2 top-1/2 h-[40vh] w-[190vw] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle_at_center,_rgba(11,110,101,0.62),_transparent_62%)] blur-3xl dark:bg-[radial-gradient(circle_at_center,_rgba(11,110,101,0.44),_transparent_62%)]" />
          <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-background to-transparent" />
        </div>

        <div className="mx-auto flex h-screen w-full max-w-4xl flex-col items-center justify-center px-6 text-center">
          <div className="translate-y-[-6vh]">
            <h1
              className={`${instrumentSans.className} text-foreground text-[clamp(3rem,9vw,5rem)] font-semibold tracking-tight`}
            >
              Weaves
            </h1>
            <p
              className={`${instrumentSans.className} mt-4 text-sm text-foreground/70 sm:text-base`}
            >
              Bringing automation &amp; creativity to your team
            </p>
          </div>
        </div>
      </section>

      {/* Section 2: Our work */}
      <section className="min-h-screen w-full snap-start bg-background py-9 text-foreground">
        <div className="mx-auto flex min-h-screen w-full max-w-[95rem] flex-col justify-center px-4 py-16 min-[481px]:px-6 min-[769px]:px-9 min-[1025px]:px-9">
          {/* Header section */}
          <div className="mb-12 grid grid-cols-1 items-center gap-8 min-[769px]:mb-16 min-[769px]:grid-cols-2 min-[769px]:gap-12 min-[1025px]:gap-52">
            <div className="min-[1025px]:-mt-24 min-[1025px]:ml-10">
              <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 mb-3">
                Weaves Studio
              </p>
              <h2 className={`${instrumentSans.className} text-[clamp(2.35rem,4.7vw,3.75rem)] font-normal leading-[1.1] tracking-tight`}>
                A design studio.
              </h2>
            </div>
            <div className="flex flex-col">
              <p className="text-base leading-tight text-foreground/70 min-[769px]:text-lg">
                We work with brands and individuals to create visuals that<br />
                truly engage audiences. By combining AI technology with<br />
                creative design, we&apos;re leading the way in this exciting<br />
                industry transformation.
              </p>
              <div className="mt-4 flex items-center gap-4 min-[769px]:mt-0 min-[769px]:gap-6">
                <div className="relative h-14 w-14 min-[769px]:h-[80px] min-[769px]:w-[80px]">
                  <ThemedLogo
                    lightSrc="/images/Image from Chronicle HQ.png"
                    darkSrc="/images/Image from Chronicle HQ.png"
                    alt="Logo 1"
                    className="object-contain"
                    darkClassName="invert"
                  />
                </div>
                <div className="relative h-14 w-14 min-[769px]:h-[80px] min-[769px]:w-[80px]">
                  <ThemedLogo
                    lightSrc="/images/Image from Chronicle HQ (1).png"
                    darkSrc="/images/Image from Chronicle HQ (1)-transparent.png"
                    alt="Logo 2"
                    className="object-contain"
                    darkClassName="invert"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Grid of 4 images */}
          <div
            className="mx-auto grid w-full grid-cols-1 gap-2 min-[481px]:grid-cols-2 min-[481px]:gap-2 min-[769px]:w-[94%] min-[769px]:grid-cols-[2.95fr_2.05fr_2.95fr_2.05fr] min-[769px]:gap-3"
            style={{ gridAutoRows: "330px" }}
          >
            <div className="relative overflow-hidden rounded-lg bg-foreground/5 min-[769px]:w-[94%] min-[769px]:justify-self-center">
              <Image
                src="/images/Merch Jacket Display Jan-Feb 2026.png"
                alt="Merch Jacket"
                fill
                className="object-cover"
              />
            </div>
            <div className="relative overflow-hidden rounded-lg bg-foreground/5">
              <Image
                src="/images/Editorial_images_Logo_Addition_2026-02-09_17-20.png"
                alt="Editorial Images"
                fill
                className="object-cover"
              />
            </div>
            <div className="relative overflow-hidden rounded-lg bg-foreground/5 min-[769px]:w-[94%] min-[769px]:justify-self-center">
              <Image
                src="/images/Exploration Minimal Editorial Setting Feb 7 2026.png"
                alt="Exploration Minimal"
                fill
                className="object-cover"
              />
            </div>
            <div className="relative overflow-hidden rounded-lg bg-foreground/5">
              <Image
                src="/images/Artisanal Coffee Photography Mar 2 2026.png"
                alt="Artisanal Coffee"
                fill
                className="object-cover"
              />
            </div>
          </div>
        </div>
      </section>

      {/* Section 3: Services */}
      <section className="min-h-screen w-full snap-start bg-background py-9 text-foreground">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col justify-start px-4 pt-2 pb-16 min-[481px]:px-6 min-[769px]:px-10 min-[1025px]:px-12">
          {/* Top: Weaves Studio + Description */}
          <div className="mb-16">
            <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 mb-8">
              Weaves Studio
            </p>
            <h2 className={`${instrumentSans.className} text-[clamp(1.9375rem,3.7vw,2.4375rem)] font-medium leading-[1.3] tracking-normal`}>
              We bring your brand to<br />
              life, blending creativity,<br />
              AI, and systems to bring<br />
              it to life at scale.
            </h2>
            
            {/* Image holders */}
            <div className="-mt-10 flex items-start min-[1025px]:ml-60 max-[1024px]:mt-10 max-[1024px]:flex-col max-[1024px]:gap-10">
              <div className="flex flex-col min-[1025px]:mr-8">
                {/* First horizontal image holder */}
                <div className="relative mt-4 h-56 w-full max-w-md overflow-hidden rounded-lg bg-foreground/5 min-[769px]:h-64 min-[1025px]:mt-20 min-[1025px]:h-50 min-[1025px]:w-75">
                  <Image
                    src="/images/Image from Chronicle HQ (2).png"
                    alt="Scale"
                    fill
                    className="object-cover"
                  />
                </div>
                
                {/* Brand text below first image */}
                <div className="mt-4 max-w-xs">
                  <h3 className="text-base font-semibold mb-1.5">Brand</h3>
                  <p className="text-base text-foreground/60 leading-snug">
                    Crafting your brand identity and applying<br />
                    it across digital, print, and physical touch<br />
                    points to create an impactful presence.
                  </p>
                </div>
              </div>
              
              {/* Second vertical image holder with Marketing text above */}
              <div className="flex flex-col max-[1024px]:gap-4 min-[1025px]:-mt-32 min-[1025px]:mr-16">
                {/* Marketing text above image */}
                <div className="mb-2 w-full max-w-md min-[1025px]:mb-6 min-[1025px]:w-[15.375rem]">
                  <h3 className="text-base font-semibold mb-1.5">Marketing</h3>
                  <p className="text-base text-foreground/60 leading-snug">
                    Bold landing pages that<br />
                    communicate value clearly,<br />
                    leaving your prospects with a<br />
                    lasting first impression.
                  </p>
                </div>
                
                {/* Vertical image holder */}
                <div className="relative h-72 w-full max-w-md overflow-hidden rounded-lg bg-foreground/5 min-[769px]:h-80 min-[1025px]:h-[25rem] min-[1025px]:w-[17rem]">
                  <Image
                    src="/images/CleanShot Sept 4 2025.png"
                    alt="Marketing"
                    fill
                    className="object-cover"
                  />
                </div>
              </div>
              
              {/* Third image holder with Product design text below */}
              <div className="flex flex-col min-[1025px]:-mt-40">
                {/* Third image holder */}
                <div className="relative h-64 w-full max-w-md overflow-hidden rounded-lg bg-foreground/5 min-[769px]:h-72 min-[1025px]:h-[18.125rem] min-[1025px]:w-[16rem]">
                  <Image
                    src="/images/CleanShot Sept 4 2025.gif"
                    alt="Product"
                    fill
                    className="object-cover"
                  />
                </div>
                
                {/* Product design text below image */}
                <div className="mt-4 w-full max-w-md min-[1025px]:w-[16rem]">
                  <h3 className="text-base font-semibold mb-1.5">Product design</h3>
                  <p className="text-base text-foreground/60 leading-snug">
                    Elevated user experiences with<br />
                    delightful micro-interactions,<br />
                    animations and attention to<br />
                    detail.
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Main content grid */}
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-[1fr_1.2fr] lg:gap-20">
            {/* Left: Large Heading */}
            <div className="flex flex-col justify-center">
            </div>

            {/* Right: Service Cards in 2x2 grid (3 cards total) */}
            <div className="grid grid-cols-2 gap-6 auto-rows-min">


            </div>
          </div>
        </div>
      </section>

      {/* Section 4: Large Image with Text */}
      <section className="min-h-screen w-full snap-start bg-background py-9 text-foreground">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-center justify-center px-0 sm:px-0 py-0">
          {/* Large image box with text at bottom right */}
          <div className="relative h-[91vh] w-[calc(100%+0.25rem)] -mx-2 overflow-hidden rounded-lg bg-foreground/5 sm:-mx-1 sm:h-[91vh] sm:w-[calc(100%+0.5rem)]">
            <Image
              src="/images/alleyway.png"
              alt="Our work showcase"
              fill
              className="object-cover"
            />
            
            {/* Text overlay at bottom right */}
            <div className="absolute right-4 bottom-4 left-4 max-w-4xl text-left min-[769px]:right-8 min-[769px]:bottom-8 min-[769px]:left-auto min-[769px]:text-right">
              <p className="text-[clamp(1rem,3.6vw,2rem)] leading-tight font-medium text-white/90">
                Logo animation, Web design, Brand identity,<br />
                Launch videos, Brand playbook, Marketing,<br />
                Product design, Landing pages
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Section 5: Process */}
      <section className="min-h-screen w-full snap-start bg-background py-9 text-foreground">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-start px-4 py-16 pt-20 min-[481px]:px-6 min-[769px]:px-10 min-[1025px]:px-12 min-[1025px]:pt-32">
          <div className="grid w-full grid-cols-1 gap-12 min-[1025px]:grid-cols-2 min-[1025px]:gap-20">
            {/* Left column: Text */}
            <div className="flex flex-col justify-start">
              <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 mb-8">
                Weaves Studio
              </p>
              
              <div className="w-full min-[1025px]:ml-8">
                <h2 className={`${instrumentSans.className} mb-6 text-[clamp(1.75rem,3.5vw,2.3rem)] font-medium leading-[1.15]`}>
                  There isn&apos;t one formula for<br />
                  powerful visuals.<br />
                  But there is a structured way to<br />
                  create them with intention.
                </h2>
                
                <p className={`${instrumentSans.className} text-[clamp(1.75rem,3.5vw,2.3rem)] font-medium leading-[1.15] text-foreground/90`}>
                  We believe that having a process for how we work together is important. This is ours
                </p>
              </div>
            </div>

            {/* Right column: Numbered list and image */}
            <div className="mt-8 flex w-full flex-col justify-center min-[1025px]:ml-[15%] min-[1025px]:w-[70%]">
              {/* Numbered list */}
              <div className="space-y-0 mb-8">
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] font-medium text-foreground">01</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-foreground">Proposal & scope sign off</span>
                  <div className="absolute top-0 left-0 h-[2px] w-full bg-foreground min-[1025px]:w-[110%]"></div>
                  <div className="absolute bottom-0 left-0 h-[2px] w-full bg-foreground min-[1025px]:w-[110%]"></div>
                </div>
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] font-medium text-foreground">02</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-foreground">Get to know your brand</span>
                  <div className="absolute bottom-0 left-0 h-[2px] w-full bg-foreground min-[1025px]:w-[110%]"></div>
                </div>
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] font-medium text-foreground">03</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-foreground">Storyboarding</span>
                  <div className="absolute bottom-0 left-0 h-[2px] w-full bg-foreground min-[1025px]:w-[110%]"></div>
                </div>
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] font-medium text-foreground">04</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-foreground">Asset development</span>
                  <div className="absolute bottom-0 left-0 h-[2px] w-full bg-foreground min-[1025px]:w-[110%]"></div>
                </div>
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] font-medium text-foreground">05</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-foreground">Refine & deliver</span>
                </div>
              </div>

              {/* Image */}
              <div className="relative h-[clamp(260px,35vh,500px)] w-full overflow-hidden rounded-lg bg-foreground/5 min-[1025px]:w-[110%]">
                <Image
                  src="/images/Flora Fashion Photoshoot Layout.jpg"
                  alt="Process"
                  fill
                  className="object-cover"
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Section 6: Selected Work */}
      <section className={`${instrumentSans.className} min-h-screen w-full snap-start bg-background py-9 text-foreground`}>
        <div className="mx-auto flex min-h-screen w-full max-w-6xl pr-0 pt-4 pb-4 pl-0 sm:pr-0 sm:pt-8 sm:pb-8 sm:pl-0">
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
                  <div className="mt-auto">
                    <div className="origin-left mb-8 text-sm font-semibold text-black transition duration-200 ease-out hover:scale-[1.16] hover:text-black dark:text-foreground dark:hover:text-foreground">
                      Weaves Studio
                    </div>

                    <h2 className="origin-left text-[clamp(3rem,8.5vw,8.5rem)] font-medium leading-[0.95] tracking-tight text-black transition duration-200 ease-out hover:scale-[1.14] hover:text-black dark:text-foreground dark:hover:text-foreground">
                      Selected<br />
                      work
                    </h2>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Section 7: Featured Work Detail */}
      <section className="min-h-screen w-full snap-start bg-background py-9 text-foreground">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-center px-4 py-16 min-[481px]:px-6 min-[769px]:px-10 min-[1025px]:px-12">
          <div className="flex w-full flex-col items-start gap-10 min-[1025px]:flex-row min-[1025px]:gap-24">
            {/* Left: Text */}
            <div className="flex h-auto max-w-md flex-col justify-between min-[1025px]:h-[610px]">
              <p className="text-xs font-medium uppercase tracking-wider text-foreground/50">
                Weaves Studio
              </p>
              
              <div className="mt-10 flex flex-1 flex-col justify-center min-[1025px]:mt-20">
                <h2 className={`${instrumentSans.className} text-[clamp(2.25rem,3.8vw,3.5rem)] font-medium leading-[1.1] tracking-tight mb-4`}>
                  Blue Tokai
                </h2>
                
                <p className={`${instrumentSans.className} text-[clamp(0.9375rem,1.4vw,1.125rem)] leading-snug text-foreground/60`}>
                  A brand campaign with a modern<br />
                  ode to street culture, tagging and<br />
                  graffiti.
                </p>
              </div>

              <div>
                <p className="text-xs font-medium text-foreground/50">
                  Brand · Advertising
                </p>
              </div>
            </div>

            {/* Right: Image with Featured work label */}
            <div className="flex w-full max-w-[800px] flex-col">
              <p className="mb-4 text-left text-xs font-medium uppercase tracking-wider text-foreground/50 min-[1025px]:text-right">
                Featured work
              </p>
              <div className="relative aspect-[4/3] w-full overflow-hidden rounded-lg bg-foreground/5 min-[1025px]:h-[610px] min-[1025px]:w-[800px] min-[1025px]:aspect-auto">
                <Image
                  src="/images/Coffee Product Photography Mar 2 2026 (1).png"
                  alt="Blue Tokai"
                  fill
                  className="object-cover"
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Section 8: Product Grid */}
      <section className="min-h-screen w-full snap-start bg-background py-9 text-foreground">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-center px-4 py-16 min-[481px]:px-6 min-[769px]:px-10 min-[1025px]:px-12">
          <div className="flex w-full flex-col items-start gap-8 min-[1025px]:flex-row min-[1025px]:gap-12">
            {/* Left: Text */}
            <div className="flex max-w-xl flex-col self-stretch min-[1025px]:max-w-xs">
              <h2 className={`${instrumentSans.className} text-[clamp(2.2rem,3.9vw,3.3rem)] font-medium leading-[1.1] tracking-tight mb-6 mt-8`}>
                Feature title
              </h2>
              
              <p className={`${instrumentSans.className} mt-8 text-[clamp(0.875rem,1.2vw,1rem)] leading-relaxed text-foreground/60 min-[1025px]:mt-[13rem]`}>
                Write a brief introduction of the app, highlight<br />
                key features and benefits to the core audience.
              </p>
            </div>

            {/* Right: Image Grid */}
            <div className="relative left-0 grid flex-1 grid-cols-1 gap-4 min-[769px]:grid-cols-2 min-[1025px]:left-8 min-[1441px]:left-16">
              {/* Column 1 - 3 images stacked */}
              <div className="flex flex-col gap-4">
                <div className="relative w-full h-[210px] overflow-hidden rounded-lg bg-foreground/5">
                  <Image
                    src="/images/Product Photography Editorial Mar 2 2026.png"
                    alt="Product 1"
                    fill
                    className="object-cover"
                  />
                </div>
                <div className="relative w-full h-[260px] overflow-hidden rounded-lg bg-foreground/5">
                  <Image
                    src="/images/Cinematic Coffee Shot Mar 2 2026.png"
                    alt="Product 2"
                    fill
                    className="object-cover"
                  />
                </div>
                <div className="relative w-full h-[210px] overflow-hidden rounded-lg bg-foreground/5">
                  <Image
                    src="/images/Coffee Photography Scene Mar 02 2026.png"
                    alt="Product 3"
                    fill
                    className="object-cover"
                  />
                </div>
              </div>

              {/* Column 2 - 4 images stacked */}
              <div className="flex flex-col gap-4">
                {/* Top image - height 2.5 units */}
                <div className="relative w-full h-[67px] overflow-hidden rounded-lg bg-foreground/5">
                  <Image
                    src="/images/Artisanal Coffee Photography Mar 2 2026.png"
                    alt="Product 4"
                    fill
                    className="object-cover object-[50%_68%]"
                  />
                </div>
                
                {/* Middle image 1 - height 10 units */}
                <div className="relative w-full h-[264px] overflow-hidden rounded-lg bg-foreground/5">
                  <Image
                    src="/images/Coffee Product Photography Mar 2 2026.png"
                    alt="Product 5"
                    fill
                    className="object-cover"
                  />
                </div>
                
                {/* Middle image 2 - height 10 units */}
                <div className="relative w-full h-[264px] overflow-hidden rounded-lg bg-foreground/5">
                  <Image
                    src="/images/Coffee Scene Integration Mar 2 2026.png"
                    alt="Product 6"
                    fill
                    className="object-cover object-[50%_45%]"
                  />
                </div>
                
                {/* Bottom image - height 2.5 units */}
                <div className="relative w-full h-[67px] overflow-hidden rounded-lg bg-foreground/5">
                  <Image
                    src="/images/Artisanal Coffee Photography Mar 2 2026.png"
                    alt="Product 7"
                    fill
                    className="object-cover object-[50%_35%]"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Section 9: Showreel */}
      <section className="min-h-screen w-full snap-start bg-background py-9 text-foreground">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-4 py-16 min-[481px]:px-6 min-[769px]:px-10 min-[1025px]:px-12">
          {/* Top: SHOWREEL label */}
          <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 mb-8">
            SHOWREEL
          </p>

          {/* Main content: Large image left, grid right */}
          <div className="flex flex-1 flex-col gap-6 min-[1025px]:flex-row min-[1025px]:gap-16">
            {/* Left: Large video/image */}
            <div className="relative h-[42vh] w-full overflow-hidden rounded-lg bg-foreground/5 min-[769px]:h-[48vh] min-[1025px]:h-auto min-[1025px]:w-[65%]">
              <Image
                src="/images/AI Generated Image.webp"
                alt="Showreel main"
                fill
                className="object-cover"
              />
            </div>

            {/* Right: Grid of 3 images */}
            <div className="grid w-full grid-cols-1 gap-4 min-[481px]:grid-cols-3 min-[481px]:gap-6 min-[1025px]:flex min-[1025px]:w-[30%] min-[1025px]:grid-cols-none min-[1025px]:flex-col">
              <div className="relative h-[24vh] w-full overflow-hidden rounded-lg bg-foreground/5 min-[1025px]:h-full">
                <Image
                  src="/images/Summer Picnic Setup 2026.png"
                  alt="Showreel 1"
                  fill
                  className="object-cover"
                />
              </div>
              <div className="relative h-[24vh] w-full overflow-hidden rounded-lg bg-foreground/5 min-[1025px]:h-full">
                <Image
                  src="/images/Beverage Ad Concept Mar 2026.png"
                  alt="Showreel 2"
                  fill
                  className="object-cover"
                />
              </div>
              <div className="relative h-[24vh] w-full overflow-hidden rounded-lg bg-foreground/5 min-[1025px]:h-full">
                <Image
                  src="/images/Picnic Scene Mar 2 2026.png"
                  alt="Showreel 3"
                  fill
                  className="object-cover"
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Section 10: Grid Quadrants */}
      <section className="min-h-screen w-full snap-start bg-background py-9 text-foreground">
        <div className="mx-auto flex min-h-screen w-full items-center justify-center px-4 py-16 min-[481px]:px-6 min-[769px]:px-10 min-[1025px]:px-12">
          {/* 2x2 Grid with dividing lines */}
          <div className="relative aspect-[4/5] w-full max-w-7xl min-[481px]:aspect-[16/11] min-[1025px]:aspect-[16/9]">
            {/* Vertical dividing line */}
            <div className="absolute top-0 bottom-0 left-1/2 z-10 w-[1px] -translate-x-1/2 bg-foreground/30"></div>
            
            {/* Horizontal dividing line */}
            <div className="absolute top-1/2 right-0 left-0 z-10 h-[1px] -translate-y-1/2 bg-foreground/30"></div>

            {/* Grid of 4 equal images with padding */}
            <div className="grid grid-cols-2 grid-rows-2 gap-8 h-full w-full p-4">
              {/* Top Left */}
              <div className="relative overflow-hidden rounded-lg bg-foreground/5">
                <Image
                  src="/images/Image from Chronicle HQ (3).png"
                  alt="Grid 1"
                  fill
                  className="object-cover"
                />
              </div>
              
              {/* Top Right */}
              <div className="relative overflow-hidden rounded-lg bg-foreground/5">
                <Image
                  src="/images/CleanShot Sept 4 2025 (1).gif"
                  alt="Grid 2"
                  fill
                  className="object-cover"
                />
              </div>
              
              {/* Bottom Left */}
              <div className="relative overflow-hidden rounded-lg bg-foreground/5">
                <Image
                  src="/images/Image from Chronicle HQ (4).png"
                  alt="Grid 3"
                  fill
                  className="object-cover"
                />
              </div>
              
              {/* Bottom Right */}
              <div className="relative overflow-hidden rounded-lg bg-foreground/5">
                <Image
                  src="/images/Image from Chronicle HQ (5).png"
                  alt="Grid 4"
                  fill
                  className="object-cover"
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Section 11: Our Values */}
      <section className="min-h-screen w-full snap-start bg-background py-9 text-foreground">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-center px-4 py-16 min-[481px]:px-6 min-[769px]:px-10 min-[1025px]:px-12">
          <div className="flex w-full flex-col items-start gap-10 min-[1025px]:flex-row min-[1025px]:gap-12">
            {/* Left: Our values heading */}
            <div className="flex w-full flex-col min-[1025px]:w-1/2">
              <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 mb-8">
                Flux Studio
              </p>
              <div className="mt-4 min-[1025px]:mt-[35%]">
                <h2 className={`${instrumentSans.className} text-[clamp(4rem,7vw,6rem)] font-medium leading-[1.05] tracking-tight text-foreground`}>
                  Our<br />
                  values
                </h2>
              </div>
            </div>

            {/* Right: Three value blocks with dividing lines */}
            <div className="relative flex w-full flex-col min-[1025px]:w-1/2">
              {/* Vertical line connecting horizontal lines */}
              <div className="absolute left-0 top-0 bottom-0 w-[1px] bg-foreground/30"></div>
              
              {/* Value 1 */}
              <div className="border-b border-foreground/30 py-6 pl-4 min-[481px]:pl-6 min-[769px]:pl-8">
                <h3 className={`${instrumentSans.className} text-[clamp(1.5rem,2.5vw,2rem)] font-medium leading-[1.2] mb-3 text-foreground`}>
                  Move mountains
                </h3>
                <p className="text-base leading-snug text-foreground/70">
                  The most powerful designs come from fearless exploration. When we<br />
                  push beyond safe choices and conventional patterns, we unlock<br />
                  possibilities that captivate audiences and elevate brands.
                </p>
                <p className="mt-2 text-base leading-snug text-foreground/70">
                  Every brief is an invitation to experiment with new techniques and<br />
                  innovative storytelling approaches that make viewers stop and say &quot;how<br />
                  did they do that?&quot;
                </p>
              </div>

              {/* Value 2 */}
              <div className="border-b border-foreground/30 py-6 pl-4 min-[481px]:pl-6 min-[769px]:pl-8">
                <h3 className={`${instrumentSans.className} text-[clamp(1.5rem,2.5vw,2rem)] font-medium leading-[1.2] mb-3 text-foreground`}>
                  Trust is the foundation
                </h3>
                <p className="text-base leading-snug text-foreground/70">
                  When we commit to a vision, timeline, or deliverable, we become<br />
                  guardians of that promise.
                </p>
                <p className="mt-2 text-base leading-snug text-foreground/70">
                  Our clients invest not just money but belief in our ability to bring their<br />
                  stories to life through motion. We honor that trust by delivering exactly<br />
                  what we promised—on time, on brand, and beyond expectations. Trust<br />
                  isn&apos;t just currency; it&apos;s the bridge to long-term partnerships.
                </p>
              </div>

              {/* Value 3 */}
              <div className="py-6 pl-4 min-[481px]:pl-6 min-[769px]:pl-8">
                <h3 className={`${instrumentSans.className} text-[clamp(1.5rem,2.5vw,2rem)] font-medium leading-[1.2] mb-3 text-foreground`}>
                  Momentum creates magic
                </h3>
                <p className="text-base text-foreground/70 leading-snug">
                  Great design isn&apos;t just about individual moments—it&apos;s about creating an unbroken flow that pulls viewers deeper into the experience. We craft experiences and brands that feel inevitable, that build anticipation, and create their own gravitational pull.
                </p>
                <p className="text-base text-foreground/70 leading-snug mt-2">
                  When every element flows naturally into the next, the entire piece becomes greater than the sum of its parts.
                </p>
              </div>
            </div>
          </div>
    </div>
      </section>

      {/* Section 12: Footer */}
      <section className="min-h-screen w-full snap-start bg-background text-foreground overflow-y-auto py-9">
        <Footer />
      </section>
    </FullpageScroll>
  );
}
