import { Instrument_Sans } from "next/font/google";
import { Footer } from "@/components/footer";
import { FullpageScroll } from "@/components/fullpage-scroll";
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
      <section className="min-h-screen w-full snap-start bg-background text-foreground py-9">
        <div className="mx-auto flex min-h-screen w-full max-w-[95rem] flex-col justify-center px-9 sm:px-18 py-16">
          {/* Header section */}
          <div className="mb-12 sm:mb-16 grid grid-cols-1 gap-8 sm:grid-cols-2 sm:gap-52 items-center">
            <div className="-mt-24">
              <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 mb-3">
                Weaves Studio
              </p>
              <h2 className={`${instrumentSans.className} text-[clamp(2.5rem,5vw,4rem)] font-normal leading-[1.1] tracking-tight`}>
                A design studio.
              </h2>
            </div>
            <div className="flex flex-col">
              <p className="text-base text-foreground/70 sm:text-lg leading-tight whitespace-nowrap">
                We work with brands and individuals to create visuals that<br />
                truly engage audiences. By combining AI technology with<br />
                creative design, we're leading the way in this exciting<br />
                industry transformation.
              </p>
              <div className="mt-0 flex items-center gap-6">
                <div className="relative h-[80px] w-[80px]">
                  <Image
                    src="/images/Image from Chronicle HQ.png"
                    alt="Logo 1"
                    fill
                    className="object-contain"
                  />
                </div>
                <div className="relative h-[80px] w-[80px]">
                  <Image
                    src="/images/Image from Chronicle HQ (1).png"
                    alt="Logo 2"
                    fill
                    className="object-contain"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Grid of 4 images */}
          <div className="grid grid-cols-2 sm:grid-cols-[2.95fr_2.05fr_2.95fr_2.05fr] gap-2 sm:gap-3" style={{ gridAutoRows: '330px' }}>
            <div className="relative overflow-hidden rounded-lg bg-foreground/5">
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
            <div className="relative overflow-hidden rounded-lg bg-foreground/5">
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
      <section className="min-h-screen w-full snap-start bg-background text-foreground py-9">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col justify-start px-6 sm:px-12 pt-2 pb-16">
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
            <div className="-mt-10 ml-60 flex items-start">
              <div className="flex flex-col mr-8">
                {/* First horizontal image holder */}
                <div className="w-75 h-50 relative overflow-hidden rounded-lg bg-foreground/5 mt-20">
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
              <div className="flex flex-col -mt-32 mr-16">
                {/* Marketing text above image */}
                <div className="mb-6 w-[15.375rem]">
                  <h3 className="text-base font-semibold mb-1.5">Marketing</h3>
                  <p className="text-base text-foreground/60 leading-snug">
                    Bold landing pages that<br />
                    communicate value clearly,<br />
                    leaving your prospects with a<br />
                    lasting first impression.
                  </p>
                </div>
                
                {/* Vertical image holder */}
                <div className="w-[17rem] h-[25rem] relative overflow-hidden rounded-lg bg-foreground/5">
                  <Image
                    src="/images/CleanShot Sept 4 2025.png"
                    alt="Marketing"
                    fill
                    className="object-cover"
                  />
                </div>
              </div>
              
              {/* Third image holder with Product design text below */}
              <div className="flex flex-col -mt-40">
                {/* Third image holder */}
                <div className="w-[16rem] h-[18.125rem] relative overflow-hidden rounded-lg bg-foreground/5">
                  <Image
                    src="/images/CleanShot Sept 4 2025.gif"
                    alt="Product"
                    fill
                    className="object-cover"
                  />
                </div>
                
                {/* Product design text below image */}
                <div className="mt-4 w-[16rem]">
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
      <section className="min-h-screen w-full snap-start bg-background text-foreground py-9">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-center justify-center px-0 sm:px-0 py-0">
          {/* Large image box with text at bottom right */}
          <div className="relative w-[calc(100%+0.25rem)] h-[91vh] -mx-2 sm:w-[calc(100%+0.5rem)] sm:h-[91vh] sm:-mx-1 overflow-hidden rounded-lg bg-foreground/5">
            <Image
              src="/images/alleyway.png"
              alt="Our work showcase"
              fill
              className="object-cover"
            />
            
            {/* Text overlay at bottom right */}
            <div className="absolute bottom-8 right-8 max-w-4xl text-right">
              <p className="text-[1.5rem] text-white/90 leading-tight font-medium sm:text-[2rem]">
                Logo animation, Web design, Brand identity,<br />
                Launch videos, Brand playbook, Marketing,<br />
                Product design, Landing pages
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Section 5: Process */}
      <section className="min-h-screen w-full snap-start bg-background text-foreground py-9">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-start px-6 sm:px-12 py-16 pt-32">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-20 w-full">
            {/* Left column: Text */}
            <div className="flex flex-col justify-start">
              <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 mb-8">
                Weaves Studio
              </p>
              
              <div className="ml-8 w-full">
                <h2 className={`${instrumentSans.className} text-[clamp(1.75rem,3.5vw,2.3rem)] font-medium leading-[1.15] mb-6 whitespace-nowrap`}>
                  There isn't one formula for<br />
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
            <div className="flex flex-col justify-center ml-[15%] w-[70%] mt-8">
              {/* Numbered list */}
              <div className="space-y-0 mb-8">
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] text-black font-medium">01</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-black">Proposal & scope sign off</span>
                  <div className="absolute top-0 left-0 w-[110%] h-[2px] bg-black"></div>
                  <div className="absolute bottom-0 left-0 w-[110%] h-[2px] bg-black"></div>
                </div>
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] text-black font-medium">02</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-black">Get to know your brand</span>
                  <div className="absolute bottom-0 left-0 w-[110%] h-[2px] bg-black"></div>
                </div>
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] text-black font-medium">03</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-black">Storyboarding</span>
                  <div className="absolute bottom-0 left-0 w-[110%] h-[2px] bg-black"></div>
                </div>
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] text-black font-medium">04</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-black">Asset development</span>
                  <div className="absolute bottom-0 left-0 w-[110%] h-[2px] bg-black"></div>
                </div>
                <div className="flex items-start gap-4 py-3 relative">
                  <span className="text-[clamp(1rem,1.8vw,1.25rem)] text-black font-medium">05</span>
                  <span className="text-[clamp(1.125rem,2vw,1.5rem)] text-black">Refine & deliver</span>
                </div>
              </div>

              {/* Image */}
              <div className="relative w-[110%] h-[clamp(300px,35vh,500px)] overflow-hidden rounded-lg bg-foreground/5">
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
      <section className={`${instrumentSans.className} min-h-screen w-full snap-start bg-background text-foreground py-9`}>
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
                    <div className="text-sm font-semibold text-black transition duration-200 ease-out hover:text-black hover:scale-[1.16] origin-left mb-8">
                      Weaves Studio
                    </div>

                    <h2 className="text-[clamp(4.5rem,8.5vw,8.5rem)] font-medium leading-[0.95] tracking-tight text-black transition duration-200 ease-out hover:text-black hover:scale-[1.14] origin-left">
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
      <section className="min-h-screen w-full snap-start bg-background text-foreground py-9">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-center px-6 sm:px-12 py-16">
          <div className="flex items-start gap-24 w-full">
            {/* Left: Text */}
            <div className="flex flex-col max-w-md h-[610px] justify-between">
              <p className="text-xs font-medium uppercase tracking-wider text-foreground/50">
                Weaves Studio
              </p>
              
              <div className="flex-1 flex flex-col justify-center mt-20">
                <h2 className={`${instrumentSans.className} text-[clamp(2.25rem,3.8vw,3.5rem)] font-medium leading-[1.1] tracking-tight mb-4`}>
                  Blue Tokai
                </h2>
                
                <p className={`${instrumentSans.className} text-[clamp(0.9375rem,1.4vw,1.125rem)] text-foreground/60 leading-snug whitespace-nowrap`}>
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
            <div className="flex flex-col">
              <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 text-right mb-4">
                Featured work
              </p>
              <div className="relative w-[800px] h-[610px] overflow-hidden rounded-lg bg-foreground/5">
                <Image
                  src="/images/Image from Chronicle HQ (3).png"
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
      <section className="min-h-screen w-full snap-start bg-background text-foreground py-9">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-center px-6 sm:px-12 py-16">
          <div className="flex items-start gap-12 w-full">
            {/* Left: Text */}
            <div className="flex flex-col self-stretch max-w-xs">
              <h2 className={`${instrumentSans.className} text-[clamp(2.2rem,3.9vw,3.3rem)] font-medium leading-[1.1] tracking-tight mb-6 mt-8`}>
                Feature title
              </h2>
              
              <p className={`${instrumentSans.className} mt-[13rem] text-[clamp(0.875rem,1.2vw,1rem)] text-foreground/60 leading-relaxed whitespace-nowrap`}>
                Write a brief introduction of the app, highlight<br />
                key features and benefits to the core audience.
              </p>
            </div>

            {/* Right: Image Grid */}
            <div className="relative left-8 sm:left-16 flex-1 grid grid-cols-2 gap-4">
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
      <section className="min-h-screen w-full snap-start bg-background text-foreground py-9">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-6 sm:px-12 py-16">
          {/* Top: SHOWREEL label */}
          <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 mb-8">
            SHOWREEL
          </p>

          {/* Main content: Large image left, grid right */}
          <div className="flex-1 flex gap-16">
            {/* Left: Large video/image */}
            <div className="relative w-[65%] overflow-hidden rounded-lg bg-foreground/5">
              <Image
                src="/images/AI Generated Image.webp"
                alt="Showreel main"
                fill
                className="object-cover"
              />
            </div>

            {/* Right: Grid of 3 images */}
            <div className="w-[30%] flex flex-col gap-6">
              <div className="relative w-full h-full overflow-hidden rounded-lg bg-foreground/5">
                <Image
                  src="/images/Summer Picnic Setup 2026.png"
                  alt="Showreel 1"
                  fill
                  className="object-cover"
                />
              </div>
              <div className="relative w-full h-full overflow-hidden rounded-lg bg-foreground/5">
                <Image
                  src="/images/Beverage Ad Concept Mar 2026.png"
                  alt="Showreel 2"
                  fill
                  className="object-cover"
                />
              </div>
              <div className="relative w-full h-full overflow-hidden rounded-lg bg-foreground/5">
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
      <section className="min-h-screen w-full snap-start bg-background text-foreground py-9">
        <div className="mx-auto flex min-h-screen w-full items-center justify-center px-6 sm:px-12 py-16">
          {/* 2x2 Grid with dividing lines */}
          <div className="relative w-full max-w-7xl aspect-[16/9]">
            {/* Vertical dividing line */}
            <div className="absolute left-1/2 top-0 bottom-0 w-[1px] bg-black/30 -translate-x-1/2 z-10"></div>
            
            {/* Horizontal dividing line */}
            <div className="absolute top-1/2 left-0 right-0 h-[1px] bg-black/30 -translate-y-1/2 z-10"></div>

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
      <section className="min-h-screen w-full snap-start bg-background text-foreground py-9">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl items-center px-6 sm:px-12 py-16">
          <div className="flex items-start gap-12 w-full">
            {/* Left: Our values heading */}
            <div className="w-1/2 flex flex-col">
              <p className="text-xs font-medium uppercase tracking-wider text-foreground/50 mb-8">
                Flux Studio
              </p>
              <div className="mt-[35%]">
                <h2 className={`${instrumentSans.className} text-[clamp(4rem,7vw,6rem)] font-medium leading-[1.05] tracking-tight text-foreground`}>
                  Our<br />
                  values
                </h2>
              </div>
            </div>

            {/* Right: Three value blocks with dividing lines */}
            <div className="w-1/2 flex flex-col relative">
              {/* Vertical line connecting horizontal lines */}
              <div className="absolute left-0 top-0 bottom-0 w-[1px] bg-foreground/30"></div>
              
              {/* Value 1 */}
              <div className="py-6 border-b border-foreground/30 pl-8">
                <h3 className={`${instrumentSans.className} text-[clamp(1.5rem,2.5vw,2rem)] font-medium leading-[1.2] mb-3 text-foreground`}>
                  Move mountains
                </h3>
                <p className="text-base text-foreground/70 leading-snug whitespace-nowrap">
                  The most powerful designs come from fearless exploration. When we<br />
                  push beyond safe choices and conventional patterns, we unlock<br />
                  possibilities that captivate audiences and elevate brands.
                </p>
                <p className="text-base text-foreground/70 leading-snug mt-2 whitespace-nowrap">
                  Every brief is an invitation to experiment with new techniques and<br />
                  innovative storytelling approaches that make viewers stop and say "how<br />
                  did they do that?"
                </p>
              </div>

              {/* Value 2 */}
              <div className="py-6 border-b border-foreground/30 pl-8">
                <h3 className={`${instrumentSans.className} text-[clamp(1.5rem,2.5vw,2rem)] font-medium leading-[1.2] mb-3 text-foreground`}>
                  Trust is the foundation
                </h3>
                <p className="text-base text-foreground/70 leading-snug whitespace-nowrap">
                  When we commit to a vision, timeline, or deliverable, we become<br />
                  guardians of that promise.
                </p>
                <p className="text-base text-foreground/70 leading-snug mt-2 whitespace-nowrap">
                  Our clients invest not just money but belief in our ability to bring their<br />
                  stories to life through motion. We honor that trust by delivering exactly<br />
                  what we promised—on time, on brand, and beyond expectations. Trust<br />
                  isn't just currency; it's the bridge to long-term partnerships.
                </p>
              </div>

              {/* Value 3 */}
              <div className="py-6 pl-8">
                <h3 className={`${instrumentSans.className} text-[clamp(1.5rem,2.5vw,2rem)] font-medium leading-[1.2] mb-3 text-foreground`}>
                  Momentum creates magic
                </h3>
                <p className="text-base text-foreground/70 leading-snug">
                  Great design isn't just about individual moments—it's about creating an unbroken flow that pulls viewers deeper into the experience. We craft experiences and brands that feel inevitable, that build anticipation, and create their own gravitational pull.
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
