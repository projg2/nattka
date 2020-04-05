# based on the work of Max Magorsch
# https://gitweb.gentoo.org/fork/bugzilla.git/commit/?id=92f934a30bdd615f9124c3107325d8884b89941a

FROM gentoo/stage3-amd64-nomultilib

RUN echo "FEATURES=\"parallel-install -ebuild-locks\"" >> /etc/portage/make.conf \
 && echo "www-servers/apache apache2_modules_version apache2_mpms_prefork" > /etc/portage/package.use/apache \
 && echo "dev-perl/Crypt-SMIME ~amd64" >> /etc/portage/package.accept_keywords \
 && echo "dev-perl/ExtUtils-CChecker ~amd64" >> /etc/portage/package.accept_keywords \
 && echo "dev-perl/GDGraph ~amd64" >> /etc/portage/package.accept_keywords \
 && echo "dev-perl/Chart ~amd64" >> /etc/portage/package.accept_keywords \
 && echo "dev-perl/GD ~amd64" >> /etc/portage/package.accept_keywords \
 && echo "dev-perl/GD-Graph3d ~amd64" >> /etc/portage/package.accept_keywords \
 && echo "dev-perl/XMLRPC-Lite ~amd64" >> /etc/portage/package.accept_keywords \
 && echo "dev-perl/Template-GD ~amd64" >> /etc/portage/package.accept_keywords \
 && echo "dev-perl/GDTextUtil ~amd64" >> /etc/portage/package.accept_keywords \
 && wget --progress=dot:mega -O - https://github.com/gentoo-mirror/gentoo/archive/master.tar.gz | tar -xz \
 && mv gentoo-master /var/db/repos/gentoo \
 && mkdir -p /var/www/localhost/htdocs \
 && wget --progress=dot:mega -O - https://gitweb.gentoo.org/fork/bugzilla.git/snapshot/master.tar.gz | tar -xz \
 && mv master /var/www/localhost/htdocs/bugzilla \
 && emerge -1v --jobs $(nproc) www-servers/apache dev-perl/CGI dev-perl/TimeDate dev-perl/DateTime dev-perl/DateTime-TimeZone dev-perl/DBI dev-perl/Template-Toolkit dev-perl/Email-Sender dev-perl/Email-MIME dev-perl/URI dev-perl/List-MoreUtils dev-perl/Math-Random-ISAAC dev-perl/JSON-XS dev-perl/Crypt-OpenPGP dev-perl/Crypt-SMIME dev-perl/HTML-Tree dev-perl/DBD-SQLite dev-perl/JSON-RPC dev-perl/Test-Taint \
 && rm -rf /var/db/repos/gentoo \
 && usermod -u 1000 apache \
 && groupmod -g 1000 apache

WORKDIR /var/www/localhost/htdocs/bugzilla

COPY bugzilla.conf /etc/apache2/vhosts.d/00_default_vhost.conf
COPY import-db.pl /var/www/localhost/htdocs/bugzilla
COPY bugzilla.sql /var/www/localhost/htdocs/bugzilla

RUN echo '$db_driver = "sqlite";' > localconfig \
 && ./checksetup.pl \
 && printf 'test@example.com\nTest developer\nabc123\nabc123\n' | ./checksetup.pl \
 && sed -i -e '/delivery/s:Sendmail:None:' data/params.json \
 && perl ./import-db.pl \
 && rm bugzilla.sql import-db.pl

CMD ["apache2", "-DFOREGROUND"]
