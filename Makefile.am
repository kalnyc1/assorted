ACLOCAL_AMFLAGS = -I m4

SUBDIRS = \
	common \
	libcerror \
	libcthreads \
	libcdata \
	libclocale \
	libcnotify \
	libuna \
	libcfile \
	libfwnt \
	libhmac \
	libcsystem \
	src \
	po

GETTEXT_FILES = \
	config.rpath \
	po/Makevars.in

EXTRA_DIST = \
	$(GETTEXT_FILES)

MAINTAINERCLEANFILES = \
	Makefile.in

libtool: @LIBTOOL_DEPS@
	cd $(srcdir) && $(SHELL) ./config.status --recheck

distclean: clean
	/bin/rm -f Makefile
	/bin/rm -f config.status
	/bin/rm -f config.cache
	/bin/rm -f config.log
	@for dir in ${subdirs}; do \
		(cd $$dir && $(MAKE) distclean) \
		|| case "$(MFLAGS)" in *k*) fail=yes;; *) exit 1;; esac; \
	done && test -z "$$fail"

splint:
	(cd $(srcdir)/libcerror && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/libcthreads && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/libcdata && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/libclocale && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/libcnotify && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/libuna && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/libcfile && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/libfwnt && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/libhmac && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/libcsystem && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/src && $(MAKE) splint $(AM_MAKEFLAGS))
	(cd $(srcdir)/po && $(MAKE) splint $(AM_MAKEFLAGS))

